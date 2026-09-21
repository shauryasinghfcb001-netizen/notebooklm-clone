#!/usr/bin/env python3
"""Generate NotebookLMClone.xcodeproj/project.pbxproj from the Swift sources.

Re-run after adding/removing files:  python3 ios/gen_project.py
Validates: unique IDs, every reference resolves, files exist, braces balance.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
APP = "NotebookLMClone"
SWIFT = sorted(p.name for p in (ROOT / APP).glob("*.swift"))
assert SWIFT, "no swift files found"

_uid = 0


def nid():
    global _uid
    _uid += 1
    return f"{_uid:024X}"


def q(v):
    if re.fullmatch(r"[A-Za-z0-9_./=:-]+", v):
        return v
    return '"' + v.replace('"', '\\"') + '"'


def arr(items):
    # items: list of (id, comment)
    inner = "".join(f"\n\t\t\t\t{i} /* {c} */," for i, c in items)
    return f"({inner}\n\t\t\t)"


def sarr(vals):
    return "(" + ", ".join(q(v) for v in vals) + ")"


def settings(d):
    inner = "".join(f"\n\t\t\t\t{k} = {v};" for k, v in d.items())
    return f"{{{inner}\n\t\t\t}}"


out = []


def emit(ident, comment, isa, props):
    out.append(f"\t\t{ident} /* {comment} */ = {{")
    out.append(f"\t\t\tisa = {isa};")
    for k, v in props:
        out.append(f"\t\t\t{k} = {v};")
    out.append("\t\t};")


def section(name):
    out.append(f"/* Begin {name} section */")


def endsection(name):
    out.append(f"/* End {name} section */")


# ---- allocate IDs ----
bf_swift = [(nid(), f) for f in SWIFT]
bf_assets = nid()
fr_swift = [(nid(), f) for f in SWIFT]
fr_plist = nid()
fr_assets = nid()
fr_app = nid()
grp_main = nid()
grp_app = nid()
grp_products = nid()
ph_sources = nid()
ph_frameworks = nid()
ph_resources = nid()
tgt = nid()
proj = nid()
cfg_proj_dbg = nid()
cfg_proj_rel = nid()
cfg_tgt_dbg = nid()
cfg_tgt_rel = nid()
list_proj = nid()
list_tgt = nid()

# ---- build file refs ----
section("PBXBuildFile")
for i, f in bf_swift:
    emit(i, f"{f} in Sources", "PBXBuildFile", [("fileRef", [x for x, n in fr_swift if n == f][0])])
emit(bf_assets, "Assets.xcassets in Resources", "PBXBuildFile", [("fileRef", fr_assets)])
endsection("PBXBuildFile")

section("PBXFileReference")
for (i, f) in fr_swift:
    emit(i, f, "PBXFileReference", [("fileEncoding", "4"), ("lastKnownFileType", "sourcecode.swift"),
                                    ("path", q(f)), ("sourceTree", '"<group>"')])
emit(fr_plist, "Info.plist", "PBXFileReference", [("fileEncoding", "4"), ("lastKnownFileType", "text.plist.xml"),
                                                  ("path", "Info.plist"), ("sourceTree", '"<group>"')])
emit(fr_assets, "Assets.xcassets", "PBXFileReference", [("lastKnownFileType", "folder.assetcatalog"),
                                                        ("path", "Assets.xcassets"), ("sourceTree", '"<group>"')])
emit(fr_app, f"{APP}.app", "PBXFileReference", [("explicitFileType", "wrapper.application"),
                                                 ("includeInIndex", "0"), ("path", q(f"{APP}.app")),
                                                 ("sourceTree", "BUILT_PRODUCTS_DIR")])
endsection("PBXFileReference")

section("PBXFrameworksBuildPhase")
emit(ph_frameworks, "Frameworks", "PBXFrameworksBuildPhase",
     [("buildActionMask", "2147483647"), ("files", arr([])), ("runOnlyForDeploymentPostprocessing", "0")])
endsection("PBXFrameworksBuildPhase")

section("PBXGroup")
emit(grp_app, APP, "PBXGroup",
     [("children", arr([(i, f) for i, f in fr_swift] + [(fr_plist, "Info.plist"), (fr_assets, "Assets.xcassets")])),
      ("path", APP), ("sourceTree", '"<group>"')])
emit(grp_products, "Products", "PBXGroup",
     [("children", arr([(fr_app, f"{APP}.app")])), ("name", "Products"), ("sourceTree", '"<group>"')])
emit(grp_main, "Project object", "PBXGroup",
     [("children", arr([(grp_app, APP), (grp_products, "Products")])),
      ("sourceTree", '"<group>"')])
endsection("PBXGroup")

section("PBXNativeTarget")
emit(tgt, APP, "PBXNativeTarget",
     [("buildConfigurationList", list_tgt),
      ("buildPhases", arr([(ph_sources, "Sources"), (ph_frameworks, "Frameworks"), (ph_resources, "Resources")])),
      ("buildRules", arr([])), ("dependencies", arr([])), ("name", APP),
      ("productName", APP), ("productReference", fr_app),
      ("productType", q("com.apple.product-type.application"))])
endsection("PBXNativeTarget")

section("PBXProject")
emit(proj, "Project object", "PBXProject",
     [("attributes", settings({
         "BuildIndependentTargetsInParallel": "1",
         "LastSwiftUpdateCheck": "1600",
         "LastUpgradeCheck": "1600",
         "TargetAttributes": settings({tgt: settings({"CreatedOnToolsVersion": "16.0"})}),
     })),
      ("buildConfigurationList", list_proj), ("compatibilityVersion", q("Xcode 15.0")),
      ("developmentRegion", "en"), ("hasScannedForEncodings", "0"),
      ("knownRegions", sarr(["en"])), ("mainGroup", grp_main), ("productRefGroup", grp_products),
      ("projectDirPath", '""'), ("projectRoot", '""'), ("targets", arr([(tgt, APP)]))])
endsection("PBXProject")

section("PBXResourcesBuildPhase")
emit(ph_resources, "Resources", "PBXResourcesBuildPhase",
     [("buildActionMask", "2147483647"), ("files", arr([(bf_assets, "Assets.xcassets in Resources")])),
      ("runOnlyForDeploymentPostprocessing", "0")])
endsection("PBXResourcesBuildPhase")

section("PBXSourcesBuildPhase")
emit(ph_sources, "Sources", "PBXSourcesBuildPhase",
     [("buildActionMask", "2147483647"),
      ("files", arr([(i, f"{f} in Sources") for i, f in bf_swift])),
      ("runOnlyForDeploymentPostprocessing", "0")])
endsection("PBXSourcesBuildPhase")

common_proj = [
    ("ALWAYS_SEARCH_USER_PATHS", "NO"),
    ("ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS", "YES"),
    ("CLANG_ANALYZER_NONNULL", "YES"),
    ("CLANG_ANALYZER_NUMBER_OBJECT_CONVERSION", "YES_AGGRESSIVE"),
    ("CLANG_CXX_LANGUAGE_STANDARD", "gnu++20"),
    ("CLANG_ENABLE_MODULES", "YES"),
    ("CLANG_ENABLE_OBJC_ARC", "YES"),
    ("CLANG_WARN_BLOCK_CAPTURE_AUTORELEASING", "YES"),
    ("CLANG_WARN_BOOL_CONVERSION", "YES"),
    ("CLANG_WARN_COMMA", "YES"),
    ("CLANG_WARN_CONSTANT_CONVERSION", "YES"),
    ("CLANG_WARN_DEPRECATED_OBJC_IMPLEMENTATIONS", "YES"),
    ("CLANG_WARN_DIRECT_OBJC_ISA_USAGE", "YES_ERROR"),
    ("CLANG_WARN_DOCUMENTATION_COMMENTS", "YES"),
    ("CLANG_WARN_EMPTY_BODY", "YES"),
    ("CLANG_WARN_ENUM_CONVERSION", "YES"),
    ("CLANG_WARN_INFINITE_RECURSION", "YES"),
    ("CLANG_WARN_INT_CONVERSION", "YES"),
    ("CLANG_WARN_NON_LITERAL_NULL_CONVERSION", "YES"),
    ("CLANG_WARN_OBJC_IMPLICIT_RETAIN_SELF", "YES"),
    ("CLANG_WARN_OBJC_LITERAL_CONVERSION", "YES"),
    ("CLANG_WARN_OBJC_ROOT_CLASS", "YES_ERROR"),
    ("CLANG_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER", "YES"),
    ("CLANG_WARN_RANGE_LOOP_ANALYSIS", "YES"),
    ("CLANG_WARN_STRICT_PROTOTYPES", "YES"),
    ("CLANG_WARN_SUSPICIOUS_MOVE", "YES"),
    ("CLANG_WARN_UNGUARDED_AVAILABILITY", "YES_AGGRESSIVE"),
    ("CLANG_WARN_UNREACHABLE_CODE", "YES"),
    ("CLANG_WARN__DUPLICATE_METHOD_MATCH", "YES"),
    ("COPY_PHASE_STRIP", "NO"),
    ("ENABLE_STRICT_OBJC_MSGSEND", "YES"),
    ("ENABLE_TESTABILITY", "YES"),
    ("ENABLE_USER_SCRIPT_SANDBOXING", "YES"),
    ("GCC_C_LANGUAGE_STANDARD", "gnu17"),
    ("GCC_DYNAMIC_NO_PIC", "NO"),
    ("GCC_NO_COMMON_BLOCKS", "YES"),
    ("GCC_WARN_64_TO_32_BIT_CONVERSION", "YES"),
    ("GCC_WARN_ABOUT_RETURN_TYPE", "YES_ERROR"),
    ("GCC_WARN_UNDECLARED_SELECTOR", "YES"),
    ("GCC_WARN_UNINITIALIZED_AUTOS", "YES_AGGRESSIVE"),
    ("GCC_WARN_UNUSED_FUNCTION", "YES"),
    ("GCC_WARN_UNUSED_VARIABLE", "YES"),
    ("IPHONEOS_DEPLOYMENT_TARGET", "17.0"),
    ("LOCALIZATION_PREFERS_STRING_CATALOGS", "YES"),
    ("MARKETING_VERSION", "1.0.0"),
    ("MTL_ENABLE_DEBUG_INFO", "INCLUDE_SOURCE"),
    ("MTL_FASTMATH", "YES"),
    ("SDKROOT", "iphoneos"),
]
proj_dbg = common_proj + [
    ("DEBUG_INFORMATION_FORMAT", "dwarf"),
    ("GCC_OPTIMIZATION_LEVEL", "0"),
    ("GCC_PREPROCESSOR_DEFINITIONS", sarr(["DEBUG=1", "$(inherited)"])),
    ("ONLY_ACTIVE_ARCH", "YES"),
    ("SWIFT_ACTIVE_COMPILATION_CONDITIONS", q("DEBUG $(inherited)")),
    ("SWIFT_OPTIMIZATION_LEVEL", "-Onone"),
]
proj_rel = common_proj + [
    ("DEBUG_INFORMATION_FORMAT", "dwarf-with-dsym"),
    ("ENABLE_NS_ASSERTIONS", "NO"),
    ("MTL_ENABLE_DEBUG_INFO", "NO"),
    ("SWIFT_COMPILATION_MODE", "wholemodule"),
    ("SWIFT_OPTIMIZATION_LEVEL", "-O"),
]
common_tgt = [
    ("ASSETCATALOG_COMPILER_APPICON_NAME", "AppIcon"),
    ("CODE_SIGN_STYLE", "Automatic"),
    ("CURRENT_PROJECT_VERSION", "1"),
    ("DEVELOPMENT_TEAM", '""'),
    ("ENABLE_PREVIEWS", "YES"),
    ("GENERATE_INFOPLIST_FILE", "NO"),
    ("INFOPLIST_FILE", q(f"{APP}/Info.plist")),
    ("IPHONEOS_DEPLOYMENT_TARGET", "17.0"),
    ("LD_RUNPATH_SEARCH_PATHS", q("@executable_path/Frameworks")),
    ("MARKETING_VERSION", "1.0.0"),
    ("PRODUCT_BUNDLE_IDENTIFIER", "com.example.notebooklmclone"),
    ("PRODUCT_NAME", q("$(TARGET_NAME)")),
    ("SWIFT_EMIT_LOC_STRINGS", "NO"),
    ("SWIFT_VERSION", "5.0"),
    ("TARGETED_DEVICE_FAMILY", q("1,2")),
]

section("XCBuildConfiguration")
emit(cfg_proj_dbg, "Debug", "XCBuildConfiguration",
     [("buildSettings", settings(dict(proj_dbg))), ("name", "Debug")])
emit(cfg_proj_rel, "Release", "XCBuildConfiguration",
     [("buildSettings", settings(dict(proj_rel))), ("name", "Release")])
emit(cfg_tgt_dbg, "Debug", "XCBuildConfiguration",
     [("buildSettings", settings(dict(common_tgt))), ("name", "Debug")])
emit(cfg_tgt_rel, "Release", "XCBuildConfiguration",
     [("buildSettings", settings(dict(common_tgt))), ("name", "Release")])
endsection("XCBuildConfiguration")

section("XCConfigurationList")
emit(list_proj, "Build configuration list for PBXProject", "XCConfigurationList",
     [("buildConfigurations", arr([(cfg_proj_dbg, "Debug"), (cfg_proj_rel, "Release")])),
      ("defaultConfigurationIsVisible", "0"), ("defaultConfigurationName", "Release")])
emit(list_tgt, "Build configuration list for PBXNativeTarget", "XCConfigurationList",
     [("buildConfigurations", arr([(cfg_tgt_dbg, "Debug"), (cfg_tgt_rel, "Release")])),
      ("defaultConfigurationIsVisible", "0"), ("defaultConfigurationName", "Release")])
endsection("XCConfigurationList")

doc = ("// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {\n\t};\n"
       "\tobjectVersion = 77;\n\tobjects = {\n" + "\n".join(out) + f"\n\t}};\n\trootObject = {proj} /* Project object */;\n}}\n")

# ---- validate ----
defs = set(re.findall(r"^\t\t([0-9A-F]{24}) /\*", doc, re.M))
refs = set(re.findall(r"\b[0-9A-F]{24}\b", doc))
assert refs <= defs, f"dangling refs: {refs - defs}"
stripped = re.sub(r"/\*.*?\*/", "", doc)
stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', stripped)
assert stripped.count("{") == stripped.count("}"), "brace imbalance"
assert stripped.count("(") == stripped.count(")"), "paren imbalance"
for f in SWIFT:
    assert (ROOT / APP / f).exists(), f
assert (ROOT / APP / "Info.plist").exists()
assert (ROOT / APP / "Assets.xcassets" / "AppIcon.appiconset" / "Contents.json").exists()
for key in ["INFOPLIST_FILE", "PRODUCT_BUNDLE_IDENTIFIER", "IPHONEOS_DEPLOYMENT_TARGET",
            "ASSETCATALOG_COMPILER_APPICON_NAME", "SWIFT_VERSION"]:
    assert key in doc, key

dest = ROOT / f"{APP}.xcodeproj" / "project.pbxproj"
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(doc)
print(f"wrote {dest} ({len(SWIFT)} swift files, {len(defs)} objects) — all refs resolve")
