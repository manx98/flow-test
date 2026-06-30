/*
Implementation of RFC 6143 §7.7 Encodings.
https://tools.ietf.org/html/rfc6143#section-7.7
*/
package vnc

import (
	"fmt"
	"io"

	"github.com/kward/go-vnc/encoding"
	"github.com/kward/go-vnc/encodings"
)

//=============================================================================
// Encodings

// An Encoding implements a method for encoding pixel data that is
// sent by the server to the client.
type Encoding interface {
	fmt.Stringer
	Marshaler

	// Read the contents of the encoded pixel data from the reader.
	// This should return a new Encoding implementation that contains
	// the proper data.
	Read(*ClientConn, *Rectangle) (Encoding, error)

	// The number that uniquely identifies this encoding type.
	Type() encodings.Encoding
}

// Encodings describes a slice of Encoding.
type Encodings []Encoding

// Verify that interfaces are honored.
var _ Marshaler = (*Encodings)(nil)

// Marshal implements the Marshaler interface.
func (e Encodings) Marshal() ([]byte, error) {
	buf := NewBuffer(nil)
	for _, enc := range e {
		if err := buf.Write(enc.Type()); err != nil {
			return nil, err
		}
	}
	return buf.Bytes(), nil
}

//-----------------------------------------------------------------------------
// Raw Encoding
//
// Raw encoding is the simplest encoding type, which is raw pixel data.
//
// See RFC 6143 §7.7.1.
// https://tools.ietf.org/html/rfc6143#section-7.7.1

// RawEncoding holds raw encoded rectangle data.
type RawEncoding struct {
	Colors []Color
	Bytes  []byte
	BPP    int
}

// Verify that interfaces are honored.
var _ Encoding = (*RawEncoding)(nil)

// Marshal implements the Encoding interface.
func (e *RawEncoding) Marshal() ([]byte, error) {
	if e.Bytes != nil {
		return e.Bytes, nil
	}
	buf := NewBuffer(nil)

	for _, c := range e.Colors {
		bytes, err := c.Marshal()
		if err != nil {
			return nil, err
		}
		if err := buf.Write(bytes); err != nil {
			return nil, err
		}
	}

	raw := &encoding.RawEncodingWire{Bytes: buf.Bytes()}
	return raw.WireMarshal()
}

// Read implements the Encoding interface.
func (*RawEncoding) Read(c *ClientConn, rect *Rectangle) (Encoding, error) {
	bytesPerPixel := int(c.pixelFormat.BPP / 8)
	n := rect.Area() * bytesPerPixel
	raw := make([]byte, n)
	if _, err := io.ReadFull(c.c, raw); err != nil {
		return nil, fmt.Errorf("unable to read rectangle with raw encoding: %s", err)
	}

	return &RawEncoding{Bytes: raw, BPP: bytesPerPixel}, nil
}

// String implements the fmt.Stringer interface.
func (*RawEncoding) String() string { return "RawEncoding" }

// Type implements the Encoding interface.
func (*RawEncoding) Type() encodings.Encoding { return encodings.Raw }

//=============================================================================
// Pseudo-Encodings
//
// Rectangles with a "pseudo-encoding" allow a server to send data to the
// client. The interpretation of the data depends on the pseudo-encoding.
//
// See RFC 6143 §7.8.
// https://tools.ietf.org/html/rfc6143#section-7.8

//-----------------------------------------------------------------------------
// DesktopSize Pseudo-Encoding
//
// When a client requests DesktopSize pseudo-encoding, it is indicating to the
// server that it can handle changes to the framebuffer size. If this encoding
// received, the client must resize its framebuffer, and drop all existing
// information stored in the framebuffer.
//
// See RFC 6143 §7.8.2.
// https://tools.ietf.org/html/rfc6143#section-7.8.2

// DesktopSizePseudoEncoding represents a desktop size message from the server.
type DesktopSizePseudoEncoding struct{}

// Verify that interfaces are honored.
var _ Encoding = (*DesktopSizePseudoEncoding)(nil)

// Marshal implements the Marshaler interface.
func (e *DesktopSizePseudoEncoding) Marshal() ([]byte, error) {
	return []byte{}, nil
}

// Read implements the Encoding interface.
func (*DesktopSizePseudoEncoding) Read(c *ClientConn, rect *Rectangle) (Encoding, error) {
	c.fbWidth = rect.Width
	c.fbHeight = rect.Height

	return &DesktopSizePseudoEncoding{}, nil
}

// String implements the fmt.Stringer interface.
func (e *DesktopSizePseudoEncoding) String() string { return "DesktopSizePseudoEncoding" }

// Type implements the Encoding interface.
func (*DesktopSizePseudoEncoding) Type() encodings.Encoding { return encodings.DesktopSizePseudo }
