# UTF-8
# Windows version resource for PyInstaller.
# Used by: trading.spec (version= parameter on EXE)

VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 0, 0, 0),
        prodvers=(1, 0, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "Certified Random"),
                StringStruct("FileDescription", "Blank Trading Terminal"),
                StringStruct("FileVersion", "1.0.0"),
                StringStruct("InternalName", "blank"),
                StringStruct("LegalCopyright",
                             "Copyright (C) 2026 Certified Random. All rights reserved."),
                StringStruct("OriginalFilename", "blank.exe"),
                StringStruct("ProductName", "Blank"),
                StringStruct("ProductVersion", "1.0.0"),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
