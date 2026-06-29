package device

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type PVEDevice struct {
	*VNCDevice
}

type pveClient struct {
	base   string
	client *http.Client
}

type pveAPIResponse struct {
	Data json.RawMessage `json:"data"`
}

type pveAuthData struct {
	Ticket string `json:"ticket"`
	CSRF   string `json:"CSRFPreventionToken"`
}

type pveVNCProxyData struct {
	Ticket string `json:"ticket"`
	Port   any    `json:"port"`
}

func NewPVEDevice(config map[string]any) (*PVEDevice, error) {
	host := stringConfig(config, "host")
	if host == "" {
		return nil, fmt.Errorf("pve device requires host")
	}
	node := stringConfig(config, "node")
	vmid := intFromConfig(config, "vmid", 0)
	if node == "" || vmid <= 0 {
		return nil, fmt.Errorf("pve device requires node and vmid")
	}
	vmtype := stringConfig(config, "vmtype")
	if vmtype == "" {
		vmtype = "qemu"
	}
	if vmtype != "qemu" && vmtype != "lxc" {
		return nil, fmt.Errorf("unsupported pve vmtype %q", vmtype)
	}
	port := intFromConfig(config, "port", 8006)
	verifyTLS := boolFromConfig(config, "verify_tls", false)
	timeout := time.Duration(intFromConfig(config, "connect_timeout", 30)) * time.Second
	client := newPVEClient(host, port, verifyTLS, timeout)
	auth, err := client.login(stringConfig(config, "username"), stringConfig(config, "password"))
	if err != nil {
		return nil, err
	}
	cookie := "PVEAuthCookie=" + auth.Ticket
	proxy, err := client.vncProxy(node, vmtype, vmid, cookie, auth.CSRF)
	if err != nil {
		return nil, err
	}
	vncPort, err := pvePort(proxy.Port)
	if err != nil {
		return nil, err
	}
	wsURL := (&url.URL{
		Scheme: "wss",
		Host:   hostPort(host, port),
		Path:   fmt.Sprintf("/api2/json/nodes/%s/%s/%d/vncwebsocket", url.PathEscape(node), url.PathEscape(vmtype), vmid),
		RawQuery: url.Values{
			"port":      {strconv.Itoa(vncPort)},
			"vncticket": {proxy.Ticket},
		}.Encode(),
	}).String()
	vncConfig := copyConfig(config)
	vncConfig["url"] = wsURL
	vncConfig["password"] = proxy.Ticket
	vncConfig["cookie"] = cookie
	vncConfig["verify_tls"] = verifyTLS
	vncConfig["insecure_tls"] = !verifyTLS
	dev, err := NewVNCDevice(vncConfig)
	if err != nil {
		return nil, err
	}
	return &PVEDevice{VNCDevice: dev}, nil
}

func newPVEClient(host string, port int, verifyTLS bool, timeout time.Duration) *pveClient {
	transport := &http.Transport{}
	if !verifyTLS {
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	return &pveClient{
		base: "https://" + hostPort(host, port),
		client: &http.Client{
			Timeout:   timeout,
			Transport: transport,
		},
	}
}

func (c *pveClient) login(username, password string) (*pveAuthData, error) {
	form := url.Values{"username": {username}, "password": {password}}
	var auth pveAuthData
	if err := c.api(context.Background(), http.MethodPost, "/api2/json/access/ticket", form, "", "", &auth); err != nil {
		return nil, err
	}
	if auth.Ticket == "" || auth.CSRF == "" {
		return nil, fmt.Errorf("pve login response missing ticket or CSRFPreventionToken")
	}
	return &auth, nil
}

func (c *pveClient) vncProxy(node, vmtype string, vmid int, cookie, csrf string) (*pveVNCProxyData, error) {
	form := url.Values{"websocket": {"1"}}
	path := fmt.Sprintf("/api2/json/nodes/%s/%s/%d/vncproxy", url.PathEscape(node), url.PathEscape(vmtype), vmid)
	var proxy pveVNCProxyData
	if err := c.api(context.Background(), http.MethodPost, path, form, cookie, csrf, &proxy); err != nil {
		return nil, err
	}
	if proxy.Ticket == "" || proxy.Port == nil {
		return nil, fmt.Errorf("pve vncproxy response missing ticket or port")
	}
	return &proxy, nil
}

func (c *pveClient) api(ctx context.Context, method, path string, form url.Values, cookie, csrf string, out any) error {
	var body io.Reader
	if form != nil {
		body = bytes.NewBufferString(form.Encode())
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, body)
	if err != nil {
		return err
	}
	if form != nil {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	if cookie != "" {
		req.Header.Set("Cookie", cookie)
	}
	if csrf != "" {
		req.Header.Set("CSRFPreventionToken", csrf)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("pve api %s failed: %d %s", path, resp.StatusCode, strings.TrimSpace(string(data)))
	}
	var envelope pveAPIResponse
	if err := json.Unmarshal(data, &envelope); err != nil {
		return err
	}
	if len(envelope.Data) == 0 {
		return fmt.Errorf("pve api %s response missing data", path)
	}
	return json.Unmarshal(envelope.Data, out)
}

func pvePort(value any) (int, error) {
	switch v := value.(type) {
	case float64:
		return int(v), nil
	case string:
		n, err := strconv.Atoi(v)
		if err != nil {
			return 0, err
		}
		return n, nil
	default:
		return 0, fmt.Errorf("unsupported pve vnc port type %T", value)
	}
}

func hostPort(host string, port int) string {
	if strings.Contains(host, ":") {
		return "[" + strings.Trim(host, "[]") + "]:" + strconv.Itoa(port)
	}
	return host + ":" + strconv.Itoa(port)
}
