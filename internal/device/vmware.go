package device

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/vmware/govmomi"
	"github.com/vmware/govmomi/find"
	"github.com/vmware/govmomi/object"
	"github.com/vmware/govmomi/vim25/types"
)

type VMwareDevice struct {
	*VNCDevice
	client *govmomi.Client
}

func NewVMwareDevice(config map[string]any) (*VMwareDevice, error) {
	host := stringConfig(config, "host")
	if host == "" {
		return nil, fmt.Errorf("vmware device requires host")
	}
	vmRef := firstStringConfig(config, "vm", "vm_name", "moid")
	if vmRef == "" {
		return nil, fmt.Errorf("vmware device requires vm, vm_name, or moid")
	}
	port := intFromConfig(config, "port", 443)
	verifyTLS := boolFromConfig(config, "verify_tls", false)
	timeout := time.Duration(intFromConfig(config, "connect_timeout", 30)) * time.Second
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	u := &url.URL{
		Scheme: "https",
		Host:   hostPort(host, port),
		Path:   "/sdk",
		User:   url.UserPassword(stringConfig(config, "username"), stringConfig(config, "password")),
	}
	client, err := govmomi.NewClient(ctx, u, !verifyTLS)
	if err != nil {
		return nil, err
	}
	vm, err := findVMwareVM(ctx, client, config, vmRef)
	if err != nil {
		_ = client.Logout(context.Background())
		return nil, err
	}
	ticket, err := vm.AcquireTicket(ctx, string(types.VirtualMachineTicketTypeWebmks))
	if err != nil {
		_ = client.Logout(context.Background())
		return nil, err
	}
	wsHost := ticket.Host
	if wsHost == "" {
		wsHost = host
	}
	wsPort := int(ticket.Port)
	if wsPort <= 0 {
		wsPort = 443
	}
	wsURL := vmwareWebMKSURL(wsHost, wsPort, ticket.Ticket)
	vncConfig := copyConfig(config)
	vncConfig["url"] = wsURL
	vncConfig["password"] = ""
	vncConfig["verify_tls"] = verifyTLS
	vncConfig["insecure_tls"] = !verifyTLS
	dev, err := NewVNCDevice(vncConfig)
	if err != nil {
		_ = client.Logout(context.Background())
		return nil, err
	}
	return &VMwareDevice{VNCDevice: dev, client: client}, nil
}

func (d *VMwareDevice) Close() error {
	if d.VNCDevice != nil {
		_ = d.VNCDevice.Close()
	}
	if d.client != nil {
		return d.client.Logout(context.Background())
	}
	return nil
}

func findVMwareVM(ctx context.Context, client *govmomi.Client, config map[string]any, vmRef string) (*object.VirtualMachine, error) {
	if moid := stringConfig(config, "moid"); moid != "" {
		ref := types.ManagedObjectReference{Type: "VirtualMachine", Value: moid}
		return object.NewVirtualMachine(client.Client, ref), nil
	}
	finder := find.NewFinder(client.Client, true)
	if dcName := stringConfig(config, "datacenter"); dcName != "" {
		dc, err := finder.Datacenter(ctx, dcName)
		if err != nil {
			return nil, err
		}
		finder.SetDatacenter(dc)
	}
	vm, err := finder.VirtualMachine(ctx, vmRef)
	if err == nil {
		return vm, nil
	}
	if !strings.Contains(vmRef, "*") && !strings.Contains(vmRef, "/") {
		return finder.VirtualMachine(ctx, "*"+vmRef+"*")
	}
	return nil, err
}

func firstStringConfig(config map[string]any, keys ...string) string {
	for _, key := range keys {
		if value := stringConfig(config, key); value != "" {
			return value
		}
	}
	return ""
}

func vmwareWebMKSURL(host string, port int, ticket string) string {
	return (&url.URL{
		Scheme: "wss",
		Host:   hostPort(host, port),
		Path:   "/ticket/" + ticket,
	}).String()
}
