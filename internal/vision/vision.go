package vision

import (
	"fmt"
	"image"
	"sort"

	"gocv.io/x/gocv"
)

type Point struct {
	X int `json:"x"`
	Y int `json:"y"`
}

type Match struct {
	X     int     `json:"x"`
	Y     int     `json:"y"`
	W     int     `json:"w,omitempty"`
	H     int     `json:"h,omitempty"`
	Score float64 `json:"score"`
}

func (m Match) Point(anchor string, dx, dy int) Point {
	x, y := m.X, m.Y
	switch anchor {
	case "top-right":
		x = m.X + m.W
		y = m.Y
	case "bottom-left":
		x = m.X
		y = m.Y + m.H
	case "bottom-right":
		x = m.X + m.W
		y = m.Y + m.H
	case "top-left":
		x = m.X
		y = m.Y
	default:
		x = m.X + m.W/2
		y = m.Y + m.H/2
	}
	return Point{X: x + dx, Y: y + dy}
}

func FindTemplate(source image.Image, template image.Image, threshold float64, mask ...image.Image) (Match, bool, error) {
	matches, err := FindAllTemplates(source, template, threshold, mask...)
	if err != nil || len(matches) == 0 {
		return Match{}, false, err
	}
	return matches[0], true, nil
}

func FindAllTemplates(source image.Image, template image.Image, threshold float64, mask ...image.Image) ([]Match, error) {
	if source == nil || template == nil {
		return nil, fmt.Errorf("source and template images are required")
	}
	if threshold <= 0 {
		threshold = 0.99
	}
	srcBounds := source.Bounds()
	tplBounds := template.Bounds()
	tplW, tplH := tplBounds.Dx(), tplBounds.Dy()
	if tplW <= 0 || tplH <= 0 {
		return nil, fmt.Errorf("template image is empty")
	}
	maskImage := firstMask(mask)
	if maskImage != nil {
		maskBounds := maskImage.Bounds()
		if maskBounds.Dx() < tplW || maskBounds.Dy() < tplH {
			return nil, fmt.Errorf("mask image must be at least template size")
		}
	}
	if srcBounds.Dx() < tplW || srcBounds.Dy() < tplH {
		return []Match{}, nil
	}

	sourceMat, err := gocv.ImageToMatRGB(source)
	if err != nil {
		return nil, err
	}
	defer sourceMat.Close()
	templateMat, err := gocv.ImageToMatRGB(template)
	if err != nil {
		return nil, err
	}
	defer templateMat.Close()
	maskMat, err := templateMaskMat(template, maskImage)
	if err != nil {
		return nil, err
	}
	defer maskMat.Close()
	result := gocv.NewMat()
	defer result.Close()
	if err := gocv.MatchTemplate(sourceMat, templateMat, &result, gocv.TmSqdiffNormed, maskMat); err != nil {
		return nil, err
	}
	matches := matchesFromResult(result, threshold, tplW, tplH)
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].Score > matches[j].Score
	})
	return suppressOverlaps(matches), nil
}

func matchesFromResult(result gocv.Mat, threshold float64, tplW int, tplH int) []Match {
	matches := []Match{}
	for row := 0; row < result.Rows(); row++ {
		for col := 0; col < result.Cols(); col++ {
			value := result.GetFloatAt(row, col)
			score := 1 - float64(value)
			if score >= threshold {
				matches = append(matches, Match{X: col, Y: row, W: tplW, H: tplH, Score: score})
			}
		}
	}
	return matches
}

func templateMaskMat(template image.Image, mask image.Image) (gocv.Mat, error) {
	tplBounds := template.Bounds()
	useMask := mask != nil
	for y := 0; y < tplBounds.Dy(); y++ {
		for x := 0; x < tplBounds.Dx(); x++ {
			_, _, _, a := template.At(tplBounds.Min.X+x, tplBounds.Min.Y+y).RGBA()
			if a < 65535 {
				useMask = true
				break
			}
		}
	}
	if !useMask {
		return gocv.NewMat(), nil
	}
	mat := gocv.NewMatWithSize(tplBounds.Dy(), tplBounds.Dx(), gocv.MatTypeCV8UC1)
	for y := 0; y < tplBounds.Dy(); y++ {
		for x := 0; x < tplBounds.Dx(); x++ {
			_, _, _, ta := template.At(tplBounds.Min.X+x, tplBounds.Min.Y+y).RGBA()
			weight := float64(ta) / 65535
			if mask != nil {
				weight *= maskWeight(mask, x, y)
			}
			if weight < 0 {
				weight = 0
			}
			if weight > 1 {
				weight = 1
			}
			mat.SetUCharAt(y, x, uint8(weight*255))
		}
	}
	return mat, nil
}

func suppressOverlaps(matches []Match) []Match {
	out := make([]Match, 0, len(matches))
	for _, match := range matches {
		overlaps := false
		for _, kept := range out {
			if rectanglesOverlap(match, kept) {
				overlaps = true
				break
			}
		}
		if !overlaps {
			out = append(out, match)
		}
	}
	return out
}

func rectanglesOverlap(a Match, b Match) bool {
	return a.X < b.X+b.W && a.X+a.W > b.X && a.Y < b.Y+b.H && a.Y+a.H > b.Y
}

func firstMask(masks []image.Image) image.Image {
	for _, mask := range masks {
		if mask != nil {
			return mask
		}
	}
	return nil
}

func maskWeight(mask image.Image, x int, y int) float64 {
	bounds := mask.Bounds()
	r, g, b, a := mask.At(bounds.Min.X+x, bounds.Min.Y+y).RGBA()
	if a == 0 {
		return 0
	}
	luma := 0.2126*float64(r) + 0.7152*float64(g) + 0.0722*float64(b)
	return (luma / 65535) * (float64(a) / 65535)
}
