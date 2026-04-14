# UTF-8
# Windows version resource for PyInstaller.
# Used by: trading.spec (version= parameter on EXE)

VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(2, 1, 1, 0),
        prodvers=(2, 1, 1, 0),
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
                StringStruct("FileVersion", "2.1.1"),
                StringStruct("InternalName", "blank"),
                StringStruct("LegalCopyright",
                             "Copyright (C) 2026 Certified Random. All rights reserved."),
                StringStruct("OriginalFilename", "blank.exe"),
                StringStruct("ProductName", "Blank"),
                StringStruct("ProductVersion", "2.1.1"),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
