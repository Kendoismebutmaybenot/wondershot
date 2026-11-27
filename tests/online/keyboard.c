#include <assert.h>
#include "hos.h"
#define HOS_H
#include "../../host/nn_swkbd.c"

int hos_vcore_away(void) { return 0; }
void hos_vcore_back(void) {}
void hos_sleep_ns(int64_t ns) { (void)ns; }
static HWND dialog_window;
static BOOL CALLBACK find_dialog(HWND window, LPARAM parameter) {
    DWORD pid=0; GetWindowThreadProcessId(window,&pid);
    WCHAR name[32]; GetClassNameW(window,name,32);
    if (pid==GetCurrentProcessId() && !wcscmp(name,L"#32770")) { *(HWND *)parameter=window; return FALSE; }
    return TRUE;
}
static DWORD WINAPI input(void *argument) {
    unsigned mode=(unsigned)(uintptr_t)argument;
    unsigned char config[0x518]={0};
    uint16_t output[10]; for (unsigned i=0;i<10;++i) output[i]=0x7777;
    uint64_t result[2]={(uintptr_t)output,10};
    config_u32(config,0,1); config_u32(config,940,4); config_u32(config,944,mode==2 ? 1 : 4);
    if (mode==2) { config_u32(config,0,0); config[957]=1; }
    Ctx c={{(uintptr_t)result,(uintptr_t)config}};
    imp__ZN2nn5swkbd12ShowKeyboardEPNS0_6StringERKNS0_15ShowKeyboardArgE(&c);
    if (mode==1) {
        assert(c.x[0]==0x29f && output[0]==0);
    } else if (mode==2) {
        assert(c.x[0]==0 && !memcmp(output,"\xc3\xa9",3));
    } else {
        assert(c.x[0]==0 && !memcmp(output,L"1234",10));
    }
    for (unsigned i=5;i<10;++i) assert(output[i]==0x7777);
    SecureZeroMemory(output,sizeof output);
    return 0;
}
int main(void) {
    for (unsigned cancel=0;cancel<3;++cancel) {
        dialog_window=NULL;
        HANDLE thread=CreateThread(NULL,0,input,(void *)(uintptr_t)cancel,0,NULL);
        assert(thread);
        for (unsigned i=0;i<200 && !dialog_window;++i) { EnumWindows(find_dialog,(LPARAM)&dialog_window); Sleep(10); }
        assert(dialog_window);
        GUITHREADINFO gui={sizeof gui};
        for (unsigned i=0;i<200;++i) {
            GetGUIThreadInfo(GetWindowThreadProcessId(dialog_window,NULL),&gui);
            if (gui.hwndFocus==GetDlgItem(dialog_window,TEXT_EDIT)) break;
            Sleep(10);
        }
        assert(gui.hwndFocus==GetDlgItem(dialog_window,TEXT_EDIT));
        if (!cancel) {
            assert(GetWindowLongPtrW(GetDlgItem(dialog_window,TEXT_EDIT),GWL_STYLE)&ES_PASSWORD);
            SendDlgItemMessageW(dialog_window,TEXT_EDIT,WM_SETTEXT,0,(LPARAM)L"abcd");
            assert(!IsWindowEnabled(GetDlgItem(dialog_window,IDOK)));
            SendDlgItemMessageW(dialog_window,TEXT_EDIT,WM_SETTEXT,0,(LPARAM)L"123");
            assert(!IsWindowEnabled(GetDlgItem(dialog_window,IDOK)));
            SendDlgItemMessageW(dialog_window,TEXT_EDIT,WM_SETTEXT,0,(LPARAM)L"");
            HWND edit=GetDlgItem(dialog_window,TEXT_EDIT);
            for (unsigned key='1';key<='4';++key) {
                LPARAM scan=1|((LPARAM)MapVirtualKeyW(key,MAPVK_VK_TO_VSC)<<16);
                PostMessageW(edit,WM_KEYDOWN,key,scan);
                PostMessageW(edit,WM_KEYUP,key,scan|0xc0000000);
            }
            for (unsigned i=0;i<200 && !IsWindowEnabled(GetDlgItem(dialog_window,IDOK));++i) Sleep(10);
            assert(IsWindowEnabled(GetDlgItem(dialog_window,IDOK)));
        }
        if (cancel==2) SendDlgItemMessageW(dialog_window,TEXT_EDIT,WM_SETTEXT,0,(LPARAM)L"\u00e9");
        PostMessageW(dialog_window,WM_COMMAND,cancel==1 ? IDCANCEL : IDOK,0);
        assert(WaitForSingleObject(thread,5000)==WAIT_OBJECT_0); CloseHandle(thread);
    }
    puts("PASS numeric validation, minimum/maximum length, bounded UTF-16/UTF-8 output and SDK cancellation result");
}
