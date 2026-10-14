/* Beat Sorter.exe: starts Beat Sorter with the Python bundled next to it
   (python\pythonw.exe -E -s -m beatsorter), so users don't need to
   install Python. Built by packaging/build_windows.ps1. */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

#define BIG 32768

static void fail(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"Beat Sorter", MB_ICONERROR | MB_OK);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR args, int show) {
    static wchar_t dir[BIG], py[BIG], cmd[BIG];
    DWORD n = GetModuleFileNameW(NULL, dir, BIG);
    if (n == 0 || n >= BIG) { fail(L"Couldn't find Beat Sorter's folder."); return 1; }
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    int smoke = args && wcsstr(args, L"--smoke-test") != NULL;
    /* the console python for the automatic test (so it can report back),
       the windowless one for normal use */
    swprintf(py, BIG, L"%s\\python\\%s", dir, smoke ? L"python.exe" : L"pythonw.exe");
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        fail(L"Some of Beat Sorter's files are missing (the python folder).\n\n"
             L"Download BeatSorter-Windows.zip again from\n"
             L"https://github.com/alienheadbill/AlienBeatSorter/releases\n"
             L"and unzip the whole folder.");
        return 1;
    }
    swprintf(cmd, BIG, L"\"%s\" -E -s -m beatsorter %s", py, args ? args : L"");

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        fail(L"Beat Sorter couldn't start. Try unzipping it to a folder you own, "
             L"such as Documents.");
        return 1;
    }
    DWORD code = 0;
    if (smoke) {  /* the automatic release test waits for the result */
        WaitForSingleObject(pi.hProcess, INFINITE);
        GetExitCodeProcess(pi.hProcess, &code);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}
