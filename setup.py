"""py2app build configuration for the NLM Scrubber GUI.

Build with:  ./build_app.sh
Or manually: python3 setup.py py2app
"""

from setuptools import setup

APP = ["nlm_scrubber_mac_gui.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "NLM Scrubber",
        "CFBundleDisplayName": "NLM Scrubber",
        "CFBundleIdentifier": "gov.nih.lhncbc.scrubber.macgui",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        # Register the app as a handler for the file types it accepts, so
        # Finder lets the user drag them onto the Dock icon and "Open With"
        # the app — both routed through ::tk::mac::OpenDocument.
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Health note",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": [
                    "public.plain-text",
                    "net.daringfireball.markdown",
                    "com.adobe.pdf",
                    "org.openxmlformats.wordprocessingml.document",
                ],
            }
        ],
    },
}

setup(
    name="NLM Scrubber",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
