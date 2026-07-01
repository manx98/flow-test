package vision

/*
#cgo linux pkg-config: opencv4
#cgo windows CXXFLAGS: -std=c++11
#cgo windows LDFLAGS: -lopencv_core -lopencv_imgproc
#include <stdlib.h>
#include "opencv_wrap.h"
*/
import "C"
import (
	"errors"
	"fmt"
	"image"
	"image/color"
	"unsafe"
)

const (
	matTypeCV8U   = 0
	matChannels1  = 0
	matChannels3  = 16
	matChannels4  = 24
	matTypeCV8UC1 = matTypeCV8U + matChannels1
	matTypeCV8UC3 = matTypeCV8U + matChannels3
	matTypeCV8UC4 = matTypeCV8U + matChannels4
)

type mat struct {
	p C.VisionMat
}

func newMat() mat {
	return mat{p: C.vision_mat_new()}
}

func newMatWithSize(rows, cols, typ int) mat {
	return mat{p: C.vision_mat_new_with_size(C.int(rows), C.int(cols), C.int(typ))}
}

func newMatFromBytes(rows, cols, typ int, data []byte) (mat, error) {
	if len(data) == 0 {
		return mat{}, errors.New("image data is empty")
	}
	p := C.CBytes(data)
	if p == nil {
		return mat{}, errors.New("failed to allocate image data")
	}
	defer C.free(p)
	m := mat{p: C.vision_mat_new_from_bytes(C.int(rows), C.int(cols), C.int(typ), (*C.uchar)(p), C.int(len(data)))}
	if m.Empty() {
		m.Close()
		return mat{}, errors.New("failed to create opencv mat")
	}
	return m, nil
}

func (m mat) Close() {
	if m.p != nil {
		C.vision_mat_close(m.p)
	}
}

func (m mat) Empty() bool {
	return m.p == nil || C.vision_mat_empty(m.p) != 0
}

func (m mat) Rows() int {
	return int(C.vision_mat_rows(m.p))
}

func (m mat) Cols() int {
	return int(C.vision_mat_cols(m.p))
}

func (m mat) GetFloatAt(row, col int) float32 {
	return float32(C.vision_mat_get_float(m.p, C.int(row), C.int(col)))
}

func (m mat) SetUCharAt(row, col int, val uint8) {
	C.vision_mat_set_uchar(m.p, C.int(row), C.int(col), C.uchar(val))
}

func matchTemplate(image, templ mat, result *mat, mask mat) error {
	msg := C.vision_match_template(image.p, templ.p, result.p, mask.p)
	if msg == nil {
		return nil
	}
	defer C.free(unsafe.Pointer(msg))
	return fmt.Errorf("opencv matchTemplate: %s", C.GoString(msg))
}

func imageToMatRGB(img image.Image) (mat, error) {
	bounds := img.Bounds()
	w, h := bounds.Dx(), bounds.Dy()
	if w <= 0 || h <= 0 {
		return mat{}, errors.New("image is empty")
	}
	if img.ColorModel() == color.RGBAModel {
		rgba, ok := img.(*image.RGBA)
		if !ok {
			return mat{}, errors.New("image color format error")
		}
		data := rgba.Pix
		if rgba.Stride != w*4 || len(data) < h*w*4 {
			data = make([]byte, h*w*4)
			for y := 0; y < h; y++ {
				copy(data[y*w*4:(y+1)*w*4], rgba.Pix[y*rgba.Stride:y*rgba.Stride+w*4])
			}
		}
		src, err := newMatFromBytes(h, w, matTypeCV8UC4, data[:h*w*4])
		if err != nil {
			return mat{}, err
		}
		defer src.Close()
		dst := newMat()
		if err := rgbaToBGR(src, &dst); err != nil {
			dst.Close()
			return mat{}, err
		}
		return dst, nil
	}
	data := make([]byte, 0, w*h*3)
	for y := bounds.Min.Y; y < bounds.Max.Y; y++ {
		for x := bounds.Min.X; x < bounds.Max.X; x++ {
			r, g, b, _ := img.At(x, y).RGBA()
			data = append(data, byte(b>>8), byte(g>>8), byte(r>>8))
		}
	}
	return newMatFromBytes(h, w, matTypeCV8UC3, data)
}

func rgbaToBGR(src mat, dst *mat) error {
	msg := C.vision_rgba_to_bgr(src.p, dst.p)
	if msg == nil {
		return nil
	}
	defer C.free(unsafe.Pointer(msg))
	return fmt.Errorf("opencv cvtColor: %s", C.GoString(msg))
}
