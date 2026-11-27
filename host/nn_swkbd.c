/* PC text entry for the Switch 2 software-keyboard SDK boundary.
   String is {guest buffer, byte capacity}; KeyboardConfig is 0x518 bytes.
   The supported SDK stores max/min length at 940/944, password flag at 948,
   and UTF-8 output flag at 957. Cancellation is Result 0x29f.
   No submitted text, password, or callback payload is written to a log. */
#include "hos.h"
#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>
#endif

static void config_u32(unsigned char *p, unsigned offset, uint32_t value) { memcpy(p+offset,&value,4); }
static uint32_t config_read(const unsigned char *p, unsigned offset) { uint32_t value; memcpy(&value,p+offset,4); return value; }
static void config_default(unsigned char *p, unsigned preset) {
    memset(p,0,0x518);
    config_u32(p,0,preset==2 ? 0 : 2);
    config_u32(p,948,preset==1);
    config_u32(p,952,preset==2 ? 0 : 1);
    p[958]=1;
    memset(p+992,0xff,32);
}
HLE(_ZN2nn5swkbd24InitializeKeyboardConfigEPNS0_14KeyboardConfigE) { if (ARG(0)) config_default(GP(ARG(0)),0); RET(0); }
HLE(_ZN2nn5swkbd10MakePresetEPNS0_14KeyboardConfigENS0_6PresetE) { if (ARG(0)) config_default(GP(ARG(0)),(unsigned)ARG(1)); RET(0); }
static void copy_text(Ctx *c, unsigned offset, unsigned capacity, int utf8) {
    if (ARG(0) && ARG(1)) {
        uint16_t *out=(uint16_t *)((unsigned char *)GP(ARG(0))+offset);
        memset(out,0,capacity*2);
#ifdef _WIN32
        if (utf8) {
            char input[1025]; unsigned count=0;
            while (count<1024 && ((const char *)GP(ARG(1)))[count]) { input[count]=((const char *)GP(ARG(1)))[count]; ++count; }
            input[count]=0;
            int length=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,input,(int)count,(WCHAR *)out,(int)capacity-1);
            if (length<0) out[0]=0;
            SecureZeroMemory(input,sizeof input);
        } else
#else
        (void)utf8;
#endif
        { const uint16_t *in=GP(ARG(1)); for (unsigned i=0;i+1<capacity && in[i];++i) out[i]=in[i]; }
    }
    RET(0);
}
HLE(_ZN2nn5swkbd13SetHeaderTextEPNS0_14KeyboardConfigEPKDs) { copy_text(c,36,65,0); }
HLE(_ZN2nn5swkbd17SetHeaderTextUtf8EPNS0_14KeyboardConfigEPKc) { copy_text(c,36,65,1); }
HLE(_ZN2nn5swkbd10SetSubTextEPNS0_14KeyboardConfigEPKDs) { copy_text(c,166,129,0); }
HLE(_ZN2nn5swkbd14SetSubTextUtf8EPNS0_14KeyboardConfigEPKc) { copy_text(c,166,129,1); }
HLE(_ZN2nn5swkbd12SetGuideTextEPNS0_14KeyboardConfigEPKDs) { copy_text(c,424,257,0); }
HLE(_ZN2nn5swkbd16SetGuideTextUtf8EPNS0_14KeyboardConfigEPKc) { copy_text(c,424,257,1); }
HLE(_ZN2nn5swkbd9SetOkTextEPNS0_14KeyboardConfigEPKDs) { copy_text(c,4,9,0); }
HLE(_ZN2nn5swkbd13SetOkTextUtf8EPNS0_14KeyboardConfigEPKc) { copy_text(c,4,9,1); }
HLE(_ZN2nn5swkbd24SetLeftOptionalSymbolKeyEPNS0_14KeyboardConfigEDs) { if (ARG(0)) { uint16_t value=(uint16_t)ARG(1); memcpy((unsigned char *)GP(ARG(0))+22,&value,2); } RET(0); }
HLE(_ZN2nn5swkbd25SetRightOptionalSymbolKeyEPNS0_14KeyboardConfigEDs) { if (ARG(0)) { uint16_t value=(uint16_t)ARG(1); memcpy((unsigned char *)GP(ARG(0))+24,&value,2); } RET(0); }

#ifdef _WIN32
enum { TEXT_EDIT=101, TEXT_GUIDE=102, FOCUS_EDIT=WM_APP+42 };
typedef struct {
    HWND owner;
    HFONT font;
    WCHAR title[80], guide[258], text[1002];
    unsigned minimum, maximum;
    int numeric, masked, accepted;
} KeyboardDialog;
static volatile LONG keyboard_busy;
static BOOL CALLBACK keyboard_owner(HWND window, LPARAM parameter) {
    DWORD pid=0; GetWindowThreadProcessId(window,&pid);
    if (pid==GetCurrentProcessId() && IsWindowVisible(window) && !GetWindow(window,GW_OWNER)) {
        *(HWND *)parameter=window; return FALSE;
    }
    return TRUE;
}
static int valid_text(KeyboardDialog *state, HWND window) {
    WCHAR text[1002];
    int count=GetDlgItemTextW(window,TEXT_EDIT,text,1002);
    int valid=count>=(int)state->minimum && count<=(int)state->maximum;
    if (state->numeric) for (int i=0;i<count;++i) if (text[i]<L'0' || text[i]>L'9') valid=0;
    SecureZeroMemory(text,sizeof text);
    return valid;
}
static INT_PTR CALLBACK keyboard_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    KeyboardDialog *state=(KeyboardDialog *)GetWindowLongPtrW(window,DWLP_USER);
    if (message==WM_INITDIALOG) {
        state=(KeyboardDialog *)lparam; SetWindowLongPtrW(window,DWLP_USER,(LONG_PTR)state);
        SetWindowTextW(window,state->title[0] ? state->title : L"Wondershot - text input");
        typedef UINT (WINAPI *WindowDpi)(HWND);
        typedef BOOL (WINAPI *AdjustDpi)(LPRECT,DWORD,BOOL,DWORD,UINT);
        HMODULE user32=GetModuleHandleW(L"user32.dll");
        WindowDpi window_dpi=(WindowDpi)GetProcAddress(user32,"GetDpiForWindow");
        AdjustDpi adjust_dpi=(AdjustDpi)GetProcAddress(user32,"AdjustWindowRectExForDpi");
        UINT dpi=window_dpi ? window_dpi(state->owner ? state->owner : window) : 96; if (!dpi) dpi=96;
        int margin=MulDiv(16,dpi,96), edit_height=MulDiv(40,dpi,96), button_height=MulDiv(36,dpi,96);
        int button_width=MulDiv(100,dpi,96), label_height=MulDiv(48,dpi,96);
        RECT size={0,0,MulDiv(600,dpi,96),MulDiv(220,dpi,96)};
        if (adjust_dpi) adjust_dpi(&size,(DWORD)GetWindowLongPtrW(window,GWL_STYLE),FALSE,(DWORD)GetWindowLongPtrW(window,GWL_EXSTYLE),dpi);
        else AdjustWindowRectEx(&size,(DWORD)GetWindowLongPtrW(window,GWL_STYLE),FALSE,(DWORD)GetWindowLongPtrW(window,GWL_EXSTYLE));
        RECT owner; if (!state->owner || !GetWindowRect(state->owner,&owner)) SystemParametersInfoW(SPI_GETWORKAREA,0,&owner,0);
        int outer_width=size.right-size.left, outer_height=size.bottom-size.top;
        SetWindowPos(window,NULL,owner.left+(owner.right-owner.left-outer_width)/2,owner.top+(owner.bottom-owner.top-outer_height)/2,outer_width,outer_height,SWP_NOZORDER);
        RECT area; GetClientRect(window,&area);
        int width=area.right, height=area.bottom;
        state->font=CreateFontW(-MulDiv(12,dpi,72),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Segoe UI");
        HFONT font=state->font ? state->font : (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        HWND label=CreateWindowW(L"STATIC",state->guide[0] ? state->guide : L"Type the text requested by the game. Enter accepts; Esc cancels.",WS_CHILD|WS_VISIBLE,margin,margin,width-2*margin,label_height,window,(HMENU)TEXT_GUIDE,NULL,NULL);
        HWND edit=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"",WS_CHILD|WS_VISIBLE|WS_TABSTOP|ES_AUTOHSCROLL|(state->numeric ? ES_NUMBER : 0)|(state->masked ? ES_PASSWORD : 0),margin,margin+label_height,width-2*margin,edit_height,window,(HMENU)TEXT_EDIT,NULL,NULL);
        HWND okay=CreateWindowW(L"BUTTON",L"OK",WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_DEFPUSHBUTTON,width-2*button_width-2*margin,height-button_height-margin,button_width,button_height,window,(HMENU)IDOK,NULL,NULL);
        HWND cancel=CreateWindowW(L"BUTTON",L"Cancel",WS_CHILD|WS_VISIBLE|WS_TABSTOP,width-button_width-margin,height-button_height-margin,button_width,button_height,window,(HMENU)IDCANCEL,NULL,NULL);
        if (!label || !edit || !okay || !cancel) { EndDialog(window,0); return TRUE; }
        for (HWND child=GetWindow(window,GW_CHILD);child;child=GetWindow(child,GW_HWNDNEXT)) SendMessageW(child,WM_SETFONT,(WPARAM)font,TRUE);
        SendMessageW(edit,EM_SETLIMITTEXT,state->maximum,0);
        EnableWindow(okay,valid_text(state,window));
        SetFocus(edit); PostMessageW(window,FOCUS_EDIT,0,0); return FALSE;
    }
    if (!state) return FALSE;
    if (message==WM_SHOWWINDOW && wparam) { PostMessageW(window,FOCUS_EDIT,0,0); return FALSE; }
    if (message==WM_ACTIVATE && LOWORD(wparam)!=WA_INACTIVE) { PostMessageW(window,FOCUS_EDIT,0,0); return FALSE; }
    if (message==FOCUS_EDIT) {
        HWND edit=GetDlgItem(window,TEXT_EDIT);
        if (edit && IsWindowVisible(window)) { SendMessageW(window,WM_NEXTDLGCTL,(WPARAM)edit,TRUE); SetFocus(edit); }
        return TRUE;
    }
    if (message==WM_COMMAND) {
        if (LOWORD(wparam)==TEXT_EDIT && HIWORD(wparam)==EN_CHANGE) { EnableWindow(GetDlgItem(window,IDOK),valid_text(state,window)); return TRUE; }
        if (LOWORD(wparam)==IDOK) {
            if (!valid_text(state,window)) return TRUE;
            GetDlgItemTextW(window,TEXT_EDIT,state->text,1002); state->accepted=1; EndDialog(window,1); return TRUE;
        }
        if (LOWORD(wparam)==IDCANCEL) { EndDialog(window,0); return TRUE; }
    }
    if (message==WM_CLOSE) { EndDialog(window,0); return TRUE; }
    return FALSE;
}
static DWORD WINAPI keyboard_thread(void *parameter) {
    KeyboardDialog *state=parameter;
    _Alignas(DWORD) unsigned char template[256]={0};
    DLGTEMPLATE *dialog=(DLGTEMPLATE *)template;
    dialog->style=WS_POPUP|WS_CAPTION|WS_SYSMENU|DS_MODALFRAME|DS_CENTER;
    dialog->cx=280; dialog->cy=100;
    WORD *next=(WORD *)(dialog+1); *next++=0; *next++=0; *next=0;
    DialogBoxIndirectParamW(GetModuleHandleW(NULL),dialog,state->owner,keyboard_proc,(LPARAM)state);
    if (state->font) { DeleteObject(state->font); state->font=NULL; }
    return 0;
}
#endif

static void show_keyboard(Ctx *c) {
    const uint64_t out=ARG(0), config=ARG(1);
    if (!out || !config) { RET(0x29f); return; }
    const uint64_t buffer=G64(out), bytes=G64(out+8);
    if (!buffer || bytes<2 || bytes>0x10000) { RET(0x29f); return; }
    memset(GP(buffer),0,(size_t)bytes);
#ifdef _WIN32
    if (InterlockedCompareExchange(&keyboard_busy,1,0)) { RET(0x29f); return; }
    const unsigned char *settings=GP(config);
    KeyboardDialog state={0};
    state.maximum=config_read(settings,940); state.minimum=config_read(settings,944);
    unsigned capacity=settings[957] ? (unsigned)(bytes-1) : (unsigned)(bytes/2-1);
    if (capacity>500) capacity=500;
    if (!state.maximum || state.maximum>capacity) state.maximum=capacity;
    if (state.minimum>state.maximum) { InterlockedExchange(&keyboard_busy,0); RET(0x29f); return; }
    state.numeric=config_read(settings,0)==1;
    state.masked=config_read(settings,948)!=0 || state.numeric;
    memcpy(state.title,settings+36,65*2); state.title[65]=0;
    memcpy(state.guide,settings+424,257*2); state.guide[257]=0;
    if (state.numeric) {
        if (state.minimum==state.maximum) swprintf(state.guide,258,L"Enter exactly %u digits (0-9). Letters are not accepted.",state.maximum);
        else swprintf(state.guide,258,L"Use numbers 0-9. Enter %u to %u digits.",state.minimum,state.maximum);
    }
    EnumWindows(keyboard_owner,(LPARAM)&state.owner);
    hos_log("swkbd: PC text input opened (type %u, allowed length %u-%u)",config_read(settings,0),state.minimum,state.maximum);
    int away=hos_vcore_away();
    HANDLE thread=CreateThread(NULL,0,keyboard_thread,&state,0,NULL);
    if (thread) { WaitForSingleObject(thread,INFINITE); CloseHandle(thread); }
    if (away) hos_vcore_back();
    uint64_t result=0x29f;
    if (state.accepted) {
        if (settings[957]) {
            if (WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,state.text,-1,GP(buffer),(int)bytes,NULL,NULL)>0) result=0;
        } else {
            size_t length=wcslen(state.text);
            if ((length+1)*2<=bytes) { memcpy(GP(buffer),state.text,(length+1)*2); result=0; }
        }
    }
    SecureZeroMemory(&state,sizeof state); InterlockedExchange(&keyboard_busy,0);
    hos_log("swkbd: PC text input %s",result ? "cancelled" : "accepted");
    RET(result);
#else
    RET(0x29f);
#endif
}
HLE(_ZN2nn5swkbd12ShowKeyboardEPNS0_6StringERKNS0_15ShowKeyboardArgE) { show_keyboard(c); }
HLE(_ZN2nn5swkbd12ShowKeyboardEPNS0_6StringERKNS0_15ShowKeyboardArgENS0_7TriggerE) { show_keyboard(c); }
