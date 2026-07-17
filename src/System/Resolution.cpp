#include <System/Resolution.hpp>
#include <dolphin/vi.h>

u16 SMSGetGameVideoWidth() { return 660; }

u16 SMSGetGameVideoHeight(u32 tvMode)
{
	u16 ret = 448;
	switch (tvMode) {
	case VI_MPAL:
	case VI_NTSC:
	case VI_EURGB60:
		ret = 448;
		break;
	case VI_PAL:
		ret = 530;
		break;
	default:
		break;
	}
	return ret;
}

u16 SMSGetTitleVideoWidth() { return 660; }

u16 SMSGetTitleVideoHeight(u32 tvMode) { return SMSGetGameVideoHeight(tvMode); }

u16 SMSGetGameRenderWidth() { return 640; }

u16 SMSGetGameRenderHeight() { return 448; }

u16 SMSGetTitleRenderWidth() { return 640; }

u16 SMSGetTitleRenderHeight() { return 448; }

u16 SMSGetGCLogoRenderWidth() { return 640; }

u16 SMSGetGCLogoRenderHeight() { return 448; }

u16 SMSGetGCLogoVideoWidth() { return 640; }

// TODO: retail calls SMSGetGameVideoHeight via a real `bl` here (not inlined),
// but MWCC inlines this call for us regardless of source phrasing tried so far
// (direct return, intermediate variable, #pragma dont_inline around the call
// statement). Possibly an inlining-budget/order quirk since GameVideoHeight is
// already inlined once above (into SMSGetTitleVideoHeight) -- unresolved.
u16 SMSGetGCLogoVideoHeight(u32 tvMode) { return SMSGetGameVideoHeight(tvMode); }
