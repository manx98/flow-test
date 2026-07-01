#include "opencv_wrap.h"

#include <cstring>
#include <cstdlib>

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

namespace {
char* copy_error(const char* message) {
    const size_t n = std::strlen(message) + 1;
    char* out = static_cast<char*>(std::malloc(n));
    if (out != nullptr) {
        std::memcpy(out, message, n);
    }
    return out;
}
}

VisionMat vision_mat_new(void) {
    return new cv::Mat();
}

VisionMat vision_mat_new_with_size(int rows, int cols, int type) {
    return new cv::Mat(rows, cols, type, 0.0);
}

VisionMat vision_mat_new_from_bytes(int rows, int cols, int type, unsigned char* data, int length) {
    cv::Mat src(rows, cols, type, data);
    if (src.total() * src.elemSize() != static_cast<size_t>(length)) {
        return new cv::Mat();
    }
    return new cv::Mat(src.clone());
}

void vision_mat_close(VisionMat mat) {
    delete static_cast<cv::Mat*>(mat);
}

int vision_mat_empty(VisionMat mat) {
    return static_cast<cv::Mat*>(mat)->empty();
}

int vision_mat_rows(VisionMat mat) {
    return static_cast<cv::Mat*>(mat)->rows;
}

int vision_mat_cols(VisionMat mat) {
    return static_cast<cv::Mat*>(mat)->cols;
}

float vision_mat_get_float(VisionMat mat, int row, int col) {
    return static_cast<cv::Mat*>(mat)->at<float>(row, col);
}

void vision_mat_set_uchar(VisionMat mat, int row, int col, unsigned char value) {
    static_cast<cv::Mat*>(mat)->at<unsigned char>(row, col) = value;
}

char* vision_rgba_to_bgr(VisionMat src, VisionMat dst) {
    try {
        cv::cvtColor(*static_cast<cv::Mat*>(src), *static_cast<cv::Mat*>(dst), cv::COLOR_RGBA2BGR);
        return nullptr;
    } catch (const cv::Exception& e) {
        return copy_error(e.what());
    }
}

char* vision_match_template(VisionMat image, VisionMat templ, VisionMat result, VisionMat mask) {
    try {
        cv::matchTemplate(*static_cast<cv::Mat*>(image),
                          *static_cast<cv::Mat*>(templ),
                          *static_cast<cv::Mat*>(result),
                          cv::TM_SQDIFF_NORMED,
                          *static_cast<cv::Mat*>(mask));
        return nullptr;
    } catch (const cv::Exception& e) {
        return copy_error(e.what());
    }
}
