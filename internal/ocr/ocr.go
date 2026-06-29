package ocr

type TextBlock struct {
	Text       string  `json:"text"`
	Confidence float64 `json:"confidence"`
	X          int     `json:"x,omitempty"`
	Y          int     `json:"y,omitempty"`
	W          int     `json:"w,omitempty"`
	H          int     `json:"h,omitempty"`
}

type TesseractConfig struct {
	Lang           string
	Config         string
	TessdataPrefix string
	MinConfidence  float64
}
