# Code Signing — Windows Verified Publisher

Without code signing, Windows SmartScreen shows "Unknown Publisher" warnings when users run the installer or exe.

## Certificate Types

| Type | Cost (approx/year) | SmartScreen Trust |
|------|---------------------|-------------------|
| **EV (Extended Validation)** | $300-600 | Immediate — no reputation period |
| **OV (Organisation Validation)** | $100-300 | Builds trust over time (downloads) |

**Recommendation:** EV certificate for immediate SmartScreen trust. Providers: DigiCert, Sectigo, GlobalSign.

## Setup

### 1. Purchase certificate

You'll receive a `.pfx` file (or USB token for EV).

### 2. Set environment variables

```
set BLANK_CERT_PATH=C:\path\to\certificate.pfx
set BLANK_CERT_PASS=your-certificate-password
```

### 3. Build

`build.bat` automatically detects `BLANK_CERT_PATH` and signs both `blank.exe` and `blank-setup.exe`.

## Manual Signing

```powershell
# Sign the exe
signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank.exe

# Sign the installer
signtool sign /f "%BLANK_CERT_PATH%" /p "%BLANK_CERT_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\blank-setup.exe
```

## Verification

```powershell
signtool verify /pa dist\blank.exe
signtool verify /pa dist\blank-setup.exe
```

## Notes

- Timestamp server (`/tr`) ensures signatures remain valid after certificate expires
- SHA256 (`/fd sha256`) is required for modern Windows
- EV certificates may require a hardware USB token (e.g. SafeNet) — not just a `.pfx` file
- `signtool.exe` is part of the Windows SDK: install "Windows SDK Signing Tools"
