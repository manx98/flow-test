//go:build linux && cgo

package device

/*
#cgo pkg-config: freerdp2 freerdp-client2 winpr2
#cgo linux LDFLAGS: -pthread

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <freerdp/freerdp.h>
#include <freerdp/addin.h>
#include <freerdp/client/channels.h>
#include <freerdp/codec/color.h>
#include <freerdp/gdi/gdi.h>
#include <freerdp/graphics.h>
#include <freerdp/input.h>
#include <freerdp/settings.h>
#include <freerdp/update.h>
#include <winpr/crt.h>
#include <winpr/synch.h>

typedef struct flow_rdp_client {
	freerdp* instance;
	HANDLE thread;
	CRITICAL_SECTION lock;
	pthread_mutex_t ready_mutex;
	pthread_cond_t ready_cond;
	int sync_initialized;
	int ready_signaled;
	volatile int stop_requested;
	int connected;
	int disconnected;
	int disconnect_called;
	int cleanup_on_thread_exit;
	int thread_created;
	int context_created;
	int gdi_initialized;
	int frame_ready;
	int content_ready;
	int cursor_visible;
	UINT32 cursor_x;
	UINT32 cursor_y;
	UINT32 cursor_hot_x;
	UINT32 cursor_hot_y;
	UINT32 cursor_width;
	UINT32 cursor_height;
	UINT32 cursor_xor_bpp;
	UINT32 cursor_xor_len;
	UINT32 cursor_and_len;
	BYTE* cursor_xor;
	BYTE* cursor_and;
	pBeginPaint previous_begin_paint;
	pEndPaint previous_end_paint;
	char error[512];
} flow_rdp_client;

typedef struct flow_rdp_context {
	rdpContext context;
	flow_rdp_client* client;
} flow_rdp_context;

static pthread_once_t flow_rdp_addin_provider_once = PTHREAD_ONCE_INIT;

static void flow_rdp_register_addin_provider_once_impl(void) {
	freerdp_register_addin_provider(freerdp_channels_load_static_addin_entry, 0);
}

static void flow_rdp_register_addin_provider_once(void) {
	pthread_once(&flow_rdp_addin_provider_once, flow_rdp_register_addin_provider_once_impl);
}

static int flow_rdp_init_sync(flow_rdp_client* client) {
	if (!client) {
		return 0;
	}
	if (pthread_mutex_init(&client->ready_mutex, NULL) != 0) {
		return 0;
	}
	if (pthread_cond_init(&client->ready_cond, NULL) != 0) {
		pthread_mutex_destroy(&client->ready_mutex);
		return 0;
	}
	client->sync_initialized = 1;
	return 1;
}

static void flow_rdp_signal_ready(flow_rdp_client* client) {
	if (!client || !client->sync_initialized) {
		return;
	}
	pthread_mutex_lock(&client->ready_mutex);
	client->ready_signaled = 1;
	pthread_cond_broadcast(&client->ready_cond);
	pthread_mutex_unlock(&client->ready_mutex);
}

static void flow_rdp_deadline_from_now(struct timespec* deadline, DWORD wait_ms) {
	clock_gettime(CLOCK_REALTIME, deadline);
	deadline->tv_sec += (time_t)(wait_ms / 1000);
	deadline->tv_nsec += (long)(wait_ms % 1000) * 1000000L;
	if (deadline->tv_nsec >= 1000000000L) {
		deadline->tv_sec += deadline->tv_nsec / 1000000000L;
		deadline->tv_nsec %= 1000000000L;
	}
}

static int flow_rdp_wait_ready(flow_rdp_client* client, DWORD wait_ms) {
	if (!client || !client->sync_initialized) {
		return 0;
	}
	struct timespec deadline;
	flow_rdp_deadline_from_now(&deadline, wait_ms);
	int rc = 0;
	pthread_mutex_lock(&client->ready_mutex);
	while (!client->ready_signaled) {
		rc = pthread_cond_timedwait(&client->ready_cond, &client->ready_mutex, &deadline);
		if (rc == ETIMEDOUT || rc != 0) {
			break;
		}
	}
	int ok = client->ready_signaled ? 1 : 0;
	pthread_mutex_unlock(&client->ready_mutex);
	return ok;
}

static void flow_rdp_request_stop(flow_rdp_client* client) {
	if (!client) {
		return;
	}
	__sync_lock_test_and_set(&client->stop_requested, 1);
}

static int flow_rdp_should_stop(flow_rdp_client* client) {
	return !client || client->stop_requested != 0;
}

static void flow_rdp_destroy_sync(flow_rdp_client* client) {
	if (!client || !client->sync_initialized) {
		return;
	}
	pthread_cond_destroy(&client->ready_cond);
	pthread_mutex_destroy(&client->ready_mutex);
	client->sync_initialized = 0;
}

static flow_rdp_client* flow_rdp_context_client(rdpContext* context) {
	if (!context) {
		return NULL;
	}
	return ((flow_rdp_context*)context)->client;
}

static void flow_rdp_set_error(flow_rdp_client* client, const char* message) {
	if (!client || !message) {
		return;
	}
	strncpy(client->error, message, sizeof(client->error) - 1);
	client->error[sizeof(client->error) - 1] = '\0';
}

static void flow_rdp_set_last_error(flow_rdp_client* client, const char* prefix) {
	if (!client || !client->instance || !client->instance->context) {
		flow_rdp_set_error(client, prefix);
		return;
	}
	UINT32 code = freerdp_get_last_error(client->instance->context);
	const char* name = freerdp_get_last_error_name(code);
	const char* text = freerdp_get_last_error_string(code);
	if (code == 0) {
		snprintf(client->error, sizeof(client->error), "%s: peer disconnected or event processing stopped without FreeRDP last error",
			prefix ? prefix : "FreeRDP error");
		return;
	}
	snprintf(client->error, sizeof(client->error), "%s: 0x%08X %s %s",
		prefix ? prefix : "FreeRDP error",
		code,
		name ? name : "",
		text ? text : "");
}

static void flow_rdp_free_cursor(flow_rdp_client* client) {
	if (!client) {
		return;
	}
	free(client->cursor_xor);
	free(client->cursor_and);
	client->cursor_xor = NULL;
	client->cursor_and = NULL;
	client->cursor_visible = 0;
	client->cursor_width = 0;
	client->cursor_height = 0;
	client->cursor_xor_len = 0;
	client->cursor_and_len = 0;
}

static BOOL flow_rdp_pointer_new(rdpContext* context, rdpPointer* pointer) {
	return TRUE;
}

static void flow_rdp_pointer_free(rdpContext* context, rdpPointer* pointer) {
}

static BOOL flow_rdp_pointer_set(rdpContext* context, const rdpPointer* pointer) {
	flow_rdp_client* client = flow_rdp_context_client(context);
	if (!client || !pointer || !pointer->xorMaskData || pointer->width == 0 || pointer->height == 0) {
		return TRUE;
	}

	BYTE* xor_data = NULL;
	BYTE* and_data = NULL;
	if (pointer->lengthXorMask > 0) {
		xor_data = (BYTE*)malloc(pointer->lengthXorMask);
		if (!xor_data) {
			return FALSE;
		}
		memcpy(xor_data, pointer->xorMaskData, pointer->lengthXorMask);
	}
	if (pointer->andMaskData && pointer->lengthAndMask > 0) {
		and_data = (BYTE*)malloc(pointer->lengthAndMask);
		if (!and_data) {
			free(xor_data);
			return FALSE;
		}
		memcpy(and_data, pointer->andMaskData, pointer->lengthAndMask);
	}

	flow_rdp_free_cursor(client);
	client->cursor_hot_x = pointer->xPos;
	client->cursor_hot_y = pointer->yPos;
	client->cursor_width = pointer->width;
	client->cursor_height = pointer->height;
	client->cursor_xor_bpp = pointer->xorBpp;
	client->cursor_xor_len = pointer->lengthXorMask;
	client->cursor_and_len = pointer->lengthAndMask;
	client->cursor_xor = xor_data;
	client->cursor_and = and_data;
	client->cursor_visible = 1;
	return TRUE;
}

static BOOL flow_rdp_pointer_set_null(rdpContext* context) {
	flow_rdp_client* client = flow_rdp_context_client(context);
	if (client) {
		client->cursor_visible = 0;
	}
	return TRUE;
}

static BOOL flow_rdp_pointer_set_default(rdpContext* context) {
	flow_rdp_client* client = flow_rdp_context_client(context);
	if (client) {
		client->cursor_visible = 0;
	}
	return TRUE;
}

static BOOL flow_rdp_pointer_set_position(rdpContext* context, UINT32 x, UINT32 y) {
	flow_rdp_client* client = flow_rdp_context_client(context);
	if (client) {
		client->cursor_x = x;
		client->cursor_y = y;
	}
	return TRUE;
}

static void flow_rdp_register_pointer(rdpContext* context) {
	if (!context || !context->graphics) {
		return;
	}
	rdpPointer* pointer = Pointer_Alloc(context);
	if (!pointer) {
		return;
	}
	pointer->New = flow_rdp_pointer_new;
	pointer->Free = flow_rdp_pointer_free;
	pointer->Set = flow_rdp_pointer_set;
	pointer->SetNull = flow_rdp_pointer_set_null;
	pointer->SetDefault = flow_rdp_pointer_set_default;
	pointer->SetPosition = flow_rdp_pointer_set_position;
	graphics_register_pointer(context->graphics, pointer);
}

static BOOL flow_rdp_pre_connect(freerdp* instance) {
	rdpSettings* settings = instance->settings;
	settings->ColorDepth = 32;
	settings->SoftwareGdi = TRUE;
	settings->FastPathOutput = TRUE;
	settings->FrameAcknowledge = 10;
	settings->LargePointerFlag = TRUE;
	settings->GlyphSupportLevel = GLYPH_SUPPORT_NONE;
	if (settings->OrderSupport) {
		settings->OrderSupport[NEG_DSTBLT_INDEX] = TRUE;
		settings->OrderSupport[NEG_PATBLT_INDEX] = TRUE;
		settings->OrderSupport[NEG_SCRBLT_INDEX] = TRUE;
		settings->OrderSupport[NEG_OPAQUE_RECT_INDEX] = TRUE;
		settings->OrderSupport[NEG_MULTIDSTBLT_INDEX] = FALSE;
		settings->OrderSupport[NEG_MULTIPATBLT_INDEX] = FALSE;
		settings->OrderSupport[NEG_MULTISCRBLT_INDEX] = FALSE;
		settings->OrderSupport[NEG_MULTIOPAQUERECT_INDEX] = TRUE;
		settings->OrderSupport[NEG_MEMBLT_INDEX] = TRUE;
		settings->OrderSupport[NEG_MEM3BLT_INDEX] = FALSE;
		settings->OrderSupport[NEG_MEMBLT_V2_INDEX] = TRUE;
		settings->OrderSupport[NEG_MEM3BLT_V2_INDEX] = FALSE;
		settings->OrderSupport[NEG_SAVEBITMAP_INDEX] = FALSE;
		settings->OrderSupport[NEG_DRAWNINEGRID_INDEX] = FALSE;
		settings->OrderSupport[NEG_MULTI_DRAWNINEGRID_INDEX] = FALSE;
		settings->OrderSupport[NEG_LINETO_INDEX] = FALSE;
		settings->OrderSupport[NEG_ATEXTOUT_INDEX] = FALSE;
		settings->OrderSupport[NEG_AEXTTEXTOUT_INDEX] = FALSE;
		settings->OrderSupport[NEG_WTEXTOUT_INDEX] = FALSE;
		settings->OrderSupport[NEG_POLYGON_SC_INDEX] = FALSE;
		settings->OrderSupport[NEG_POLYGON_CB_INDEX] = FALSE;
		settings->OrderSupport[NEG_POLYLINE_INDEX] = FALSE;
		settings->OrderSupport[NEG_ELLIPSE_SC_INDEX] = FALSE;
		settings->OrderSupport[NEG_ELLIPSE_CB_INDEX] = FALSE;
		settings->OrderSupport[NEG_GLYPH_INDEX_INDEX] = FALSE;
		settings->OrderSupport[NEG_GLYPH_WEXTTEXTOUT_INDEX] = FALSE;
		settings->OrderSupport[NEG_GLYPH_WLONGTEXTOUT_INDEX] = FALSE;
		settings->OrderSupport[NEG_GLYPH_WLONGEXTTEXTOUT_INDEX] = FALSE;
		settings->OrderSupport[NEG_FAST_INDEX_INDEX] = FALSE;
		settings->OrderSupport[NEG_FAST_GLYPH_INDEX] = FALSE;
	}
	return TRUE;
}

static BOOL flow_rdp_begin_paint(rdpContext* context) {
	flow_rdp_client* client = flow_rdp_context_client(context);
	if (client && client->previous_begin_paint) {
		return client->previous_begin_paint(context);
	}
	return TRUE;
}

static BOOL flow_rdp_end_paint(rdpContext* context) {
	flow_rdp_client* client = flow_rdp_context_client(context);
	BOOL ok = TRUE;
	if (client && client->previous_end_paint) {
		ok = client->previous_end_paint(context);
	}
	if (client && context && context->gdi && context->gdi->primary_buffer) {
		client->frame_ready = 1;
	}
	return ok;
}

static int flow_rdp_has_content(const unsigned char* buffer, int width, int height, int stride) {
	if (!buffer || width <= 0 || height <= 0 || stride <= 0) {
		return 0;
	}
	int step_y = height > 48 ? height / 48 : 1;
	int step_x = width > 64 ? width / 64 : 1;
	for (int y = 0; y < height; y += step_y) {
		const unsigned char* row = buffer + y * stride;
		for (int x = 0; x < width; x += step_x) {
			const unsigned char* px = row + x * 4;
			if (px[0] || px[1] || px[2]) {
				return 1;
			}
		}
	}
	return 0;
}

static BOOL flow_rdp_post_connect(freerdp* instance) {
	if (!gdi_init(instance, PIXEL_FORMAT_BGRA32)) {
		return FALSE;
	}
	flow_rdp_context* context = instance && instance->context ? (flow_rdp_context*)instance->context : NULL;
	flow_rdp_client* client = context ? context->client : NULL;
	if (client) {
		client->gdi_initialized = 1;
	}
	if (context && context->client) {
		if (instance->update) {
			context->client->previous_begin_paint = instance->update->BeginPaint;
			context->client->previous_end_paint = instance->update->EndPaint;
			instance->update->BeginPaint = flow_rdp_begin_paint;
			instance->update->EndPaint = flow_rdp_end_paint;
		}
		flow_rdp_register_pointer(instance->context);
		context->client->connected = 1;
		flow_rdp_signal_ready(context->client);
	}
	return TRUE;
}

static void flow_rdp_post_disconnect(freerdp* instance) {
	if (!instance) {
		return;
	}
	flow_rdp_context* context = instance->context ? (flow_rdp_context*)instance->context : NULL;
	flow_rdp_client* client = context ? context->client : NULL;
	if (client && instance->update) {
		if (client->previous_begin_paint) {
			instance->update->BeginPaint = client->previous_begin_paint;
			client->previous_begin_paint = NULL;
		}
		if (client->previous_end_paint) {
			instance->update->EndPaint = client->previous_end_paint;
			client->previous_end_paint = NULL;
		}
	}
	if (instance->context && instance->context->gdi) {
		gdi_free(instance);
		if (client) {
			client->gdi_initialized = 0;
		}
	}
	if (client) {
		client->frame_ready = 0;
		client->content_ready = 0;
		flow_rdp_free_cursor(client);
	}
}

static void flow_rdp_disconnect_locked(flow_rdp_client* client) {
	if (!client || !client->instance || client->disconnect_called) {
		return;
	}
	client->disconnect_called = 1;
	freerdp_disconnect(client->instance);
}

static void flow_rdp_destroy_client(flow_rdp_client* client, BOOL close_thread_handle) {
	if (!client) {
		return;
	}
	if (close_thread_handle && client->thread) {
		CloseHandle(client->thread);
		client->thread = NULL;
		client->thread_created = 0;
	}
	if (client->instance) {
		if (client->gdi_initialized && client->instance->context && client->instance->context->gdi) {
			gdi_free(client->instance);
			client->gdi_initialized = 0;
		}
		if (client->context_created) {
			freerdp_context_free(client->instance);
			client->context_created = 0;
		}
		freerdp_free(client->instance);
		client->instance = NULL;
	}
	flow_rdp_destroy_sync(client);
	DeleteCriticalSection(&client->lock);
	flow_rdp_free_cursor(client);
	free(client);
}

static void flow_rdp_maybe_destroy_orphaned_client(flow_rdp_client* client) {
	if (!client) {
		return;
	}
	int cleanup = 0;
	EnterCriticalSection(&client->lock);
	cleanup = client->cleanup_on_thread_exit;
	LeaveCriticalSection(&client->lock);
	if (cleanup) {
		flow_rdp_destroy_client(client, FALSE);
	}
}

static DWORD WINAPI flow_rdp_loop(LPVOID arg) {
	flow_rdp_client* client = (flow_rdp_client*)arg;
	if (!client || !client->instance) {
		return 1;
	}

	DWORD ret = 0;
	if (!freerdp_connect(client->instance)) {
		flow_rdp_set_last_error(client, "freerdp_connect failed");
		ret = 1;
		goto disconnect;
	}

	while (!flow_rdp_should_stop(client)) {
		HANDLE events[64];
		DWORD count = freerdp_get_event_handles(client->instance->context, events, 64);
		if (count == 0 || count > 64) {
			flow_rdp_set_error(client, "freerdp_get_event_handles failed");
			ret = 1;
			break;
		}
		WaitForMultipleObjects(count, events, FALSE, 100);
		EnterCriticalSection(&client->lock);
		BOOL ok = freerdp_check_event_handles(client->instance->context);
		LeaveCriticalSection(&client->lock);
		if (!ok) {
			flow_rdp_set_last_error(client, "freerdp_check_event_handles failed");
			ret = 1;
			break;
		}
		EnterCriticalSection(&client->lock);
		ok = freerdp_channels_process_pending_messages(client->instance);
		LeaveCriticalSection(&client->lock);
		if (!ok) {
			flow_rdp_set_last_error(client, "freerdp_channels_process_pending_messages failed");
			ret = 1;
			break;
		}
	}

 disconnect:
	EnterCriticalSection(&client->lock);
	client->disconnected = 1;
	flow_rdp_disconnect_locked(client);
	client->connected = 0;
	LeaveCriticalSection(&client->lock);
	flow_rdp_signal_ready(client);
	flow_rdp_maybe_destroy_orphaned_client(client);
	return ret;
}

static void flow_rdp_apply_security(rdpSettings* settings, const char* auth) {
	settings->NegotiateSecurityLayer = TRUE;
	settings->NlaSecurity = TRUE;
	settings->TlsSecurity = TRUE;
	settings->RdpSecurity = TRUE;
	if (!auth || auth[0] == '\0' || strcmp(auth, "auto") == 0 || strcmp(auth, "negotiate") == 0) {
		return;
	}
	settings->NegotiateSecurityLayer = FALSE;
	settings->NlaSecurity = strcmp(auth, "nla") == 0 || strcmp(auth, "hybrid") == 0;
	settings->TlsSecurity = strcmp(auth, "tls") == 0 || strcmp(auth, "ssl") == 0;
	settings->RdpSecurity = strcmp(auth, "rdp") == 0 || strcmp(auth, "standard") == 0;
}

static flow_rdp_client* flow_rdp_new(
	const char* host,
	int port,
	const char* username,
	const char* password,
	const char* domain,
	const char* auth,
	int width,
	int height,
	int timeout_seconds,
	char* err,
	int err_len
) {
	flow_rdp_register_addin_provider_once();
	flow_rdp_client* client = (flow_rdp_client*)calloc(1, sizeof(flow_rdp_client));
	if (!client) {
		snprintf(err, err_len, "allocate RDP client failed");
		return NULL;
	}
	InitializeCriticalSection(&client->lock);
	if (!flow_rdp_init_sync(client)) {
		snprintf(err, err_len, "create RDP pthread synchronization objects failed");
		goto fail;
	}

	client->instance = freerdp_new();
	if (!client->instance) {
		snprintf(err, err_len, "freerdp_new failed");
		goto fail;
	}
	client->instance->PreConnect = flow_rdp_pre_connect;
	client->instance->PostConnect = flow_rdp_post_connect;
	client->instance->PostDisconnect = flow_rdp_post_disconnect;
	client->instance->ContextSize = sizeof(flow_rdp_context);
	if (!freerdp_context_new(client->instance)) {
		snprintf(err, err_len, "freerdp_context_new failed");
		goto fail;
	}
	client->context_created = 1;
	((flow_rdp_context*)client->instance->context)->client = client;

	rdpSettings* settings = client->instance->settings;
	settings->ServerHostname = _strdup(host);
	settings->ServerPort = port;
	settings->Username = _strdup(username ? username : "");
	settings->Password = _strdup(password ? password : "");
	settings->Domain = _strdup(domain ? domain : "");
	settings->DesktopWidth = width;
	settings->DesktopHeight = height;
	settings->ColorDepth = 32;
	settings->IgnoreCertificate = TRUE;
	settings->AuthenticationOnly = FALSE;
	settings->ProxyType = PROXY_TYPE_IGNORE;
	settings->GatewayEnabled = FALSE;
	settings->GatewayUsageMethod = TSC_PROXY_MODE_NONE_DIRECT;
	settings->SupportGraphicsPipeline = FALSE;
	settings->RemoteFxCodec = FALSE;
	settings->RemoteFxOnly = FALSE;
	settings->RemoteFxImageCodec = FALSE;
	settings->GfxH264 = FALSE;
	settings->GfxAVC444 = FALSE;
	settings->GfxAVC444v2 = FALSE;
	settings->GfxProgressive = FALSE;
	settings->GfxProgressiveV2 = FALSE;
	settings->BitmapCacheEnabled = TRUE;
	settings->BitmapCacheV3Enabled = TRUE;
	settings->BitmapCachePersistEnabled = FALSE;
	flow_rdp_apply_security(settings, auth);

	client->thread = CreateThread(NULL, 0, flow_rdp_loop, client, 0, NULL);
	if (!client->thread) {
		snprintf(err, err_len, "create RDP worker thread failed");
		goto fail;
	}
	client->thread_created = 1;
	DWORD wait_ms = timeout_seconds > 0 ? (DWORD)timeout_seconds * 1000 : 60000;
	if (!flow_rdp_wait_ready(client, wait_ms)) {
		snprintf(err, err_len, "timeout waiting for RDP connection");
		goto fail;
	}
	if (!client->connected) {
		snprintf(err, err_len, "%s", client->error[0] ? client->error : "RDP connection failed");
		goto fail;
	}
	return client;

fail:
	if (client) {
		if (client->thread) {
			flow_rdp_request_stop(client);
			DWORD wr = WaitForSingleObject(client->thread, 5000);
			if (wr != WAIT_OBJECT_0) {
				EnterCriticalSection(&client->lock);
				client->cleanup_on_thread_exit = 1;
				LeaveCriticalSection(&client->lock);
				CloseHandle(client->thread);
				client->thread = NULL;
				client->thread_created = 0;
				return NULL;
			}
			CloseHandle(client->thread);
			client->thread = NULL;
			client->thread_created = 0;
		}
		flow_rdp_destroy_client(client, FALSE);
	}
	return NULL;
}

static void flow_rdp_free(flow_rdp_client* client) {
	if (!client) {
		return;
	}
	flow_rdp_request_stop(client);
	if (client->thread) {
		WaitForSingleObject(client->thread, INFINITE);
	}
	flow_rdp_destroy_client(client, TRUE);
}

static int flow_rdp_cursor_and_bit(const BYTE* mask, UINT32 len, UINT32 width, UINT32 x, UINT32 y) {
	if (!mask) {
		return 0;
	}
	UINT32 stride = (width + 7) / 8;
	UINT32 idx = y * stride + x / 8;
	if (idx >= len) {
		return 0;
	}
	return (mask[idx] & (0x80 >> (x % 8))) != 0;
}

static void flow_rdp_blend_cursor(flow_rdp_client* client, unsigned char* dst, int width, int height, int stride) {
	if (!client || !dst || !client->cursor_visible || !client->cursor_xor || client->cursor_xor_bpp != 32 ||
	    client->cursor_width == 0 || client->cursor_height == 0) {
		return;
	}
	UINT32 src_stride = client->cursor_width * 4;
	if (client->cursor_xor_len < src_stride * client->cursor_height) {
		return;
	}
	int left = (int)client->cursor_x - (int)client->cursor_hot_x;
	int top = (int)client->cursor_y - (int)client->cursor_hot_y;
	for (UINT32 y = 0; y < client->cursor_height; y++) {
		int dy = top + (int)y;
		if (dy < 0 || dy >= height) {
			continue;
		}
		UINT32 sy = client->cursor_height - 1 - y;
		for (UINT32 x = 0; x < client->cursor_width; x++) {
			int dx = left + (int)x;
			if (dx < 0 || dx >= width) {
				continue;
			}
			const BYTE* src = client->cursor_xor + sy * src_stride + x * 4;
			BYTE b = src[0];
			BYTE g = src[1];
			BYTE r = src[2];
			BYTE a = src[3];
			if (a == 0 && flow_rdp_cursor_and_bit(client->cursor_and, client->cursor_and_len, client->cursor_width, x, sy)) {
				continue;
			}
			unsigned char* out = dst + dy * stride + dx * 4;
			if (a == 0) {
				continue;
			}
			if (a == 255) {
				out[0] = r;
				out[1] = g;
				out[2] = b;
				out[3] = 255;
				continue;
			}
			out[0] = (unsigned char)((r * a + out[0] * (255 - a)) / 255);
			out[1] = (unsigned char)((g * a + out[1] * (255 - a)) / 255);
			out[2] = (unsigned char)((b * a + out[2] * (255 - a)) / 255);
			out[3] = 255;
		}
	}
}

static int flow_rdp_copy_frame(flow_rdp_client* client, unsigned char* dst, int dst_len, int* out_width, int* out_height) {
	if (!client || !client->instance || !client->instance->context || !client->instance->context->gdi) {
		return -1;
	}
	EnterCriticalSection(&client->lock);
	if (client->disconnected) {
		LeaveCriticalSection(&client->lock);
		return -3;
	}
	if (!client->frame_ready) {
		LeaveCriticalSection(&client->lock);
		return -4;
	}
	rdpGdi* gdi = client->instance->context->gdi;
	int width = gdi->width;
	int height = gdi->height;
	int src_stride = gdi->stride;
	int dst_stride = width * 4;
	int need = dst_stride * height;
	if (!gdi->primary_buffer || src_stride <= 0 || dst_len < need) {
		LeaveCriticalSection(&client->lock);
		return -2;
	}
	if (!client->content_ready) {
		if (!flow_rdp_has_content(gdi->primary_buffer, width, height, src_stride)) {
			LeaveCriticalSection(&client->lock);
			return -5;
		}
		client->content_ready = 1;
	}
	for (int y = 0; y < height; y++) {
		unsigned char* src_row = gdi->primary_buffer + y * src_stride;
		unsigned char* dst_row = dst + y * dst_stride;
		for (int x = 0; x < width; x++) {
			unsigned char b = src_row[x * 4 + 0];
			unsigned char g = src_row[x * 4 + 1];
			unsigned char r = src_row[x * 4 + 2];
			unsigned char a = src_row[x * 4 + 3];
			dst_row[x * 4 + 0] = r;
			dst_row[x * 4 + 1] = g;
			dst_row[x * 4 + 2] = b;
			dst_row[x * 4 + 3] = a ? a : 255;
		}
	}
	flow_rdp_blend_cursor(client, dst, width, height, dst_stride);
	*out_width = width;
	*out_height = height;
	LeaveCriticalSection(&client->lock);
	return 0;
}

static int flow_rdp_is_disconnected(flow_rdp_client* client) {
	if (!client) {
		return 1;
	}
	return client->disconnected != 0;
}

static const char* flow_rdp_error(flow_rdp_client* client) {
	if (!client || !client->error[0]) {
		return "";
	}
	return client->error;
}

static int flow_rdp_mouse(flow_rdp_client* client, UINT16 flags, UINT16 x, UINT16 y) {
	if (!client || !client->instance || !client->instance->input) {
		return -1;
	}
	EnterCriticalSection(&client->lock);
	BOOL ok = client->instance->input->MouseEvent(client->instance->input, flags, x, y);
	if (ok && !(flags & PTR_FLAGS_WHEEL)) {
		client->cursor_x = x;
		client->cursor_y = y;
	}
	LeaveCriticalSection(&client->lock);
	return ok ? 0 : -1;
}

static int flow_rdp_key(flow_rdp_client* client, UINT16 flags, UINT16 code) {
	if (!client || !client->instance || !client->instance->input) {
		return -1;
	}
	EnterCriticalSection(&client->lock);
	BOOL ok = client->instance->input->KeyboardEvent(client->instance->input, flags, code);
	LeaveCriticalSection(&client->lock);
	return ok ? 0 : -1;
}
*/
import "C"

import (
	"context"
	"fmt"
	"image"
	"sync"
	"time"
	"unsafe"
)

type RDPDevice struct {
	client    *C.flow_rdp_client
	width     int
	height    int
	mu        sync.Mutex
	lastFrame *image.RGBA
}

func NewRDPDevice(config map[string]any) (Device, error) {
	cfg, err := parseRDPConfig(config)
	if err != nil {
		return nil, err
	}
	host := C.CString(cfg.Host)
	username := C.CString(cfg.Username)
	password := C.CString(cfg.Password)
	domain := C.CString(cfg.Domain)
	auth := C.CString(cfg.Auth)
	defer C.free(unsafe.Pointer(host))
	defer C.free(unsafe.Pointer(username))
	defer C.free(unsafe.Pointer(password))
	defer C.free(unsafe.Pointer(domain))
	defer C.free(unsafe.Pointer(auth))

	errBuf := make([]byte, 512)
	client := C.flow_rdp_new(
		host,
		C.int(cfg.Port),
		username,
		password,
		domain,
		auth,
		C.int(cfg.Width),
		C.int(cfg.Height),
		C.int(cfg.ConnectTimeout.Seconds()),
		(*C.char)(unsafe.Pointer(&errBuf[0])),
		C.int(len(errBuf)),
	)
	if client == nil {
		return nil, fmt.Errorf("freerdp connect %s failed: %s", cfg.Address(), cStringFromBuffer(errBuf))
	}
	dev := &RDPDevice{client: client, width: cfg.Width, height: cfg.Height}
	if cfg.FirstUpdateTimeout > 0 {
		if err := waitForFirstRDPCapture(context.Background(), dev, cfg.FirstUpdateTimeout); err != nil {
			_ = dev.Close()
			return nil, err
		}
	}
	return dev, nil
}

func waitForFirstRDPCapture(ctx context.Context, dev *RDPDevice, timeout time.Duration) error {
	var img *image.RGBA
	if err := dev.Capture(ctx, &img); err == nil {
		return nil
	}
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	var lastErr error
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline.C:
			if lastErr != nil {
				return fmt.Errorf("timeout waiting for first RDP frame: %w", lastErr)
			}
			return fmt.Errorf("timeout waiting for first RDP frame")
		case <-ticker.C:
			if err := dev.Capture(ctx, &img); err == nil {
				return nil
			} else {
				lastErr = err
			}
		}
	}
}

func (d *RDPDevice) Capture(_ context.Context, dst **image.RGBA) error {
	if d == nil {
		return fmt.Errorf("rdp device is closed")
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.client == nil {
		return fmt.Errorf("rdp device is closed")
	}
	img := EnsureRGBA(dst, image.Rect(0, 0, d.width, d.height))
	var w C.int
	var h C.int
	if rc := C.flow_rdp_copy_frame(d.client, (*C.uchar)(unsafe.Pointer(&img.Pix[0])), C.int(len(img.Pix)), &w, &h); rc != 0 {
		if d.lastFrame != nil {
			img := EnsureRGBA(dst, d.lastFrame.Bounds())
			copy(img.Pix, d.lastFrame.Pix)
			return nil
		}
		return fmt.Errorf("freerdp capture failed: %d %s", int(rc), C.GoString(C.flow_rdp_error(d.client)))
	}
	width := int(w)
	height := int(h)
	if width != d.width || height != d.height {
		img.Rect = image.Rect(0, 0, width, height)
		img.Stride = width * 4
		img.Pix = img.Pix[:width*height*4]
	}
	d.lastFrame = img
	return nil
}

func (d *RDPDevice) Size() (int, int) {
	if d == nil {
		return 0, 0
	}
	return d.width, d.height
}

func (d *RDPDevice) MouseMove(_ context.Context, x, y int) error {
	return d.mouse(C.PTR_FLAGS_MOVE, x, y)
}

func (d *RDPDevice) MouseDown(_ context.Context, button Button, x, y int) error {
	return d.mouse(rdpMouseButtonFlag(button)|C.PTR_FLAGS_DOWN, x, y)
}

func (d *RDPDevice) MouseUp(_ context.Context, button Button, x, y int) error {
	return d.mouse(rdpMouseButtonFlag(button), x, y)
}

func (d *RDPDevice) MouseWheel(_ context.Context, delta int) error {
	flags := C.UINT16(C.PTR_FLAGS_WHEEL)
	if delta < 0 {
		flags |= C.PTR_FLAGS_WHEEL_NEGATIVE
		delta = -delta
	}
	if delta == 0 {
		delta = 120
	} else if delta < 120 {
		delta *= 120
	}
	flags |= C.UINT16(delta & 0x01ff)
	return d.mouse(flags, 0, 0)
}

func (d *RDPDevice) KeyDown(_ context.Context, key Key) error {
	return d.key(key, true)
}

func (d *RDPDevice) KeyUp(_ context.Context, key Key) error {
	return d.key(key, false)
}

func (d *RDPDevice) TypeText(ctx context.Context, text string) error {
	for _, r := range text {
		sc, ok := rdpScanCode(Key(string(r)))
		if !ok {
			return fmt.Errorf("unsupported RDP text character %q", r)
		}
		if sc.Shift {
			if err := d.keyCode(rdpKeyCode{Code: 0x2a}, true); err != nil {
				return err
			}
		}
		if err := d.KeyDown(ctx, Key(string(r))); err != nil {
			return err
		}
		if err := d.KeyUp(ctx, Key(string(r))); err != nil {
			return err
		}
		if sc.Shift {
			if err := d.keyCode(rdpKeyCode{Code: 0x2a}, false); err != nil {
				return err
			}
		}
	}
	return nil
}

func (d *RDPDevice) Close() error {
	if d == nil {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.client != nil {
		client := d.client
		d.client = nil
		d.lastFrame = nil
		C.flow_rdp_free(client)
	}
	d.lastFrame = nil
	return nil
}

func (d *RDPDevice) mouse(flags C.UINT16, x, y int) error {
	if d == nil {
		return fmt.Errorf("rdp device is closed")
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.client == nil {
		return fmt.Errorf("rdp device is closed")
	}
	if C.flow_rdp_is_disconnected(d.client) != 0 {
		return fmt.Errorf("rdp device disconnected: %s", C.GoString(C.flow_rdp_error(d.client)))
	}
	if rc := C.flow_rdp_mouse(d.client, flags, C.UINT16(x), C.UINT16(y)); rc != 0 {
		return fmt.Errorf("freerdp mouse event failed: %d", int(rc))
	}
	return nil
}

func (d *RDPDevice) key(key Key, down bool) error {
	sc, ok := rdpScanCode(key)
	if !ok {
		return fmt.Errorf("unsupported RDP key %q", key)
	}
	return d.keyCode(sc, down)
}

func (d *RDPDevice) keyCode(sc rdpKeyCode, down bool) error {
	if d == nil {
		return fmt.Errorf("rdp device is closed")
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.client == nil {
		return fmt.Errorf("rdp device is closed")
	}
	if C.flow_rdp_is_disconnected(d.client) != 0 {
		return fmt.Errorf("rdp device disconnected: %s", C.GoString(C.flow_rdp_error(d.client)))
	}
	flags := C.UINT16(0)
	if !down {
		flags |= C.KBD_FLAGS_RELEASE
	}
	if sc.Extended {
		flags |= C.KBD_FLAGS_EXTENDED
	}
	if rc := C.flow_rdp_key(d.client, flags, C.UINT16(sc.Code)); rc != 0 {
		return fmt.Errorf("freerdp key event failed: %d", int(rc))
	}
	return nil
}

func rdpMouseButtonFlag(button Button) C.UINT16 {
	switch button {
	case ButtonMiddle:
		return C.PTR_FLAGS_BUTTON3
	case ButtonRight:
		return C.PTR_FLAGS_BUTTON2
	default:
		return C.PTR_FLAGS_BUTTON1
	}
}

func cStringFromBuffer(buf []byte) string {
	for i, b := range buf {
		if b == 0 {
			return string(buf[:i])
		}
	}
	return string(buf)
}
