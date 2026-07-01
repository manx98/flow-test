#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef void* VisionMat;

VisionMat vision_mat_new(void);
VisionMat vision_mat_new_with_size(int rows, int cols, int type);
VisionMat vision_mat_new_from_bytes(int rows, int cols, int type, unsigned char* data, int length);
void vision_mat_close(VisionMat mat);
int vision_mat_empty(VisionMat mat);
int vision_mat_rows(VisionMat mat);
int vision_mat_cols(VisionMat mat);
float vision_mat_get_float(VisionMat mat, int row, int col);
void vision_mat_set_uchar(VisionMat mat, int row, int col, unsigned char value);
char* vision_rgba_to_bgr(VisionMat src, VisionMat dst);
char* vision_match_template(VisionMat image, VisionMat templ, VisionMat result, VisionMat mask);

#ifdef __cplusplus
}
#endif
