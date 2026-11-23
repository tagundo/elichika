"use strict";
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var Il2Cpp;
(function (Il2Cpp) {
    /**
     * The **core** object where all the necessary IL2CPP native functions are
     * held. \
     * `frida-il2cpp-bridge` is built around this object by providing an
     * easy-to-use abstraction layer: the user isn't expected to use it directly,
     * but it can in case of advanced use cases.
     *
     * The APIs depends on the Unity version, hence some of them may be
     * unavailable; moreover, they are searched by **name** (e.g.
     * `il2cpp_class_from_name`) hence they might get stripped, hidden or
     * renamed by a nasty obfuscator.
     *
     * However, it is possible to override or set the handle of any of the
     * exports by using a global variable:
     * ```ts
     * declare global {
     *     let IL2CPP_EXPORTS: Record<string, () => NativePointer>;
     * }
     *
     * IL2CPP_EXPORTS = {
     *     il2cpp_image_get_class: () => Il2Cpp.module.base.add(0x1204c),
     *     il2cpp_class_get_parent: () => {
     *         return Memory.scanSync(Il2Cpp.module.base, Il2Cpp.module.size, "2f 10 ee 10 34 a8")[0].address;
     *     },
     * };
     *
     * Il2Cpp.perform(() => {
     *     // ...
     * });
     * ```
     */
    Il2Cpp.api = {
        get alloc() {
            return r("il2cpp_alloc", "pointer", ["size_t"]);
        },
        get arrayGetLength() {
            return r("il2cpp_array_length", "uint32", ["pointer"]);
        },
        get arrayNew() {
            return r("il2cpp_array_new", "pointer", ["pointer", "uint32"]);
        },
        get assemblyGetImage() {
            return r("il2cpp_assembly_get_image", "pointer", ["pointer"]);
        },
        get classForEach() {
            return r("il2cpp_class_for_each", "void", ["pointer", "pointer"]);
        },
        get classFromName() {
            return r("il2cpp_class_from_name", "pointer", ["pointer", "pointer", "pointer"]);
        },
        get classFromObject() {
            return r("il2cpp_class_from_system_type", "pointer", ["pointer"]);
        },
        get classGetArrayClass() {
            return r("il2cpp_array_class_get", "pointer", ["pointer", "uint32"]);
        },
        get classGetArrayElementSize() {
            return r("il2cpp_class_array_element_size", "int", ["pointer"]);
        },
        get classGetAssemblyName() {
            return r("il2cpp_class_get_assemblyname", "pointer", ["pointer"]);
        },
        get classGetBaseType() {
            return r("il2cpp_class_enum_basetype", "pointer", ["pointer"]);
        },
        get classGetDeclaringType() {
            return r("il2cpp_class_get_declaring_type", "pointer", ["pointer"]);
        },
        get classGetElementClass() {
            return r("il2cpp_class_get_element_class", "pointer", ["pointer"]);
        },
        get classGetFieldFromName() {
            return r("il2cpp_class_get_field_from_name", "pointer", ["pointer", "pointer"]);
        },
        get classGetFields() {
            return r("il2cpp_class_get_fields", "pointer", ["pointer", "pointer"]);
        },
        get classGetFlags() {
            return r("il2cpp_class_get_flags", "int", ["pointer"]);
        },
        get classGetImage() {
            return r("il2cpp_class_get_image", "pointer", ["pointer"]);
        },
        get classGetInstanceSize() {
            return r("il2cpp_class_instance_size", "int32", ["pointer"]);
        },
        get classGetInterfaces() {
            return r("il2cpp_class_get_interfaces", "pointer", ["pointer", "pointer"]);
        },
        get classGetMethodFromName() {
            return r("il2cpp_class_get_method_from_name", "pointer", ["pointer", "pointer", "int"]);
        },
        get classGetMethods() {
            return r("il2cpp_class_get_methods", "pointer", ["pointer", "pointer"]);
        },
        get classGetName() {
            return r("il2cpp_class_get_name", "pointer", ["pointer"]);
        },
        get classGetNamespace() {
            return r("il2cpp_class_get_namespace", "pointer", ["pointer"]);
        },
        get classGetNestedClasses() {
            return r("il2cpp_class_get_nested_types", "pointer", ["pointer", "pointer"]);
        },
        get classGetParent() {
            return r("il2cpp_class_get_parent", "pointer", ["pointer"]);
        },
        get classGetStaticFieldData() {
            return r("il2cpp_class_get_static_field_data", "pointer", ["pointer"]);
        },
        get classGetValueTypeSize() {
            return r("il2cpp_class_value_size", "int32", ["pointer", "pointer"]);
        },
        get classGetType() {
            return r("il2cpp_class_get_type", "pointer", ["pointer"]);
        },
        get classHasReferences() {
            return r("il2cpp_class_has_references", "bool", ["pointer"]);
        },
        get classInitialize() {
            return r("il2cpp_runtime_class_init", "void", ["pointer"]);
        },
        get classIsAbstract() {
            return r("il2cpp_class_is_abstract", "bool", ["pointer"]);
        },
        get classIsAssignableFrom() {
            return r("il2cpp_class_is_assignable_from", "bool", ["pointer", "pointer"]);
        },
        get classIsBlittable() {
            return r("il2cpp_class_is_blittable", "bool", ["pointer"]);
        },
        get classIsEnum() {
            return r("il2cpp_class_is_enum", "bool", ["pointer"]);
        },
        get classIsGeneric() {
            return r("il2cpp_class_is_generic", "bool", ["pointer"]);
        },
        get classIsInflated() {
            return r("il2cpp_class_is_inflated", "bool", ["pointer"]);
        },
        get classIsInterface() {
            return r("il2cpp_class_is_interface", "bool", ["pointer"]);
        },
        get classIsSubclassOf() {
            return r("il2cpp_class_is_subclass_of", "bool", ["pointer", "pointer", "bool"]);
        },
        get classIsValueType() {
            return r("il2cpp_class_is_valuetype", "bool", ["pointer"]);
        },
        get domainGetAssemblyFromName() {
            return r("il2cpp_domain_assembly_open", "pointer", ["pointer", "pointer"]);
        },
        get domainGet() {
            return r("il2cpp_domain_get", "pointer", []);
        },
        get domainGetAssemblies() {
            return r("il2cpp_domain_get_assemblies", "pointer", ["pointer", "pointer"]);
        },
        get fieldGetClass() {
            return r("il2cpp_field_get_parent", "pointer", ["pointer"]);
        },
        get fieldGetFlags() {
            return r("il2cpp_field_get_flags", "int", ["pointer"]);
        },
        get fieldGetName() {
            return r("il2cpp_field_get_name", "pointer", ["pointer"]);
        },
        get fieldGetOffset() {
            return r("il2cpp_field_get_offset", "int32", ["pointer"]);
        },
        get fieldGetStaticValue() {
            return r("il2cpp_field_static_get_value", "void", ["pointer", "pointer"]);
        },
        get fieldGetType() {
            return r("il2cpp_field_get_type", "pointer", ["pointer"]);
        },
        get fieldSetStaticValue() {
            return r("il2cpp_field_static_set_value", "void", ["pointer", "pointer"]);
        },
        get free() {
            return r("il2cpp_free", "void", ["pointer"]);
        },
        get gcCollect() {
            return r("il2cpp_gc_collect", "void", ["int"]);
        },
        get gcCollectALittle() {
            return r("il2cpp_gc_collect_a_little", "void", []);
        },
        get gcDisable() {
            return r("il2cpp_gc_disable", "void", []);
        },
        get gcEnable() {
            return r("il2cpp_gc_enable", "void", []);
        },
        get gcGetHeapSize() {
            return r("il2cpp_gc_get_heap_size", "int64", []);
        },
        get gcGetMaxTimeSlice() {
            return r("il2cpp_gc_get_max_time_slice_ns", "int64", []);
        },
        get gcGetUsedSize() {
            return r("il2cpp_gc_get_used_size", "int64", []);
        },
        get gcHandleGetTarget() {
            return r("il2cpp_gchandle_get_target", "pointer", ["uint32"]);
        },
        get gcHandleFree() {
            return r("il2cpp_gchandle_free", "void", ["uint32"]);
        },
        get gcHandleNew() {
            return r("il2cpp_gchandle_new", "uint32", ["pointer", "bool"]);
        },
        get gcHandleNewWeakRef() {
            return r("il2cpp_gchandle_new_weakref", "uint32", ["pointer", "bool"]);
        },
        get gcIsDisabled() {
            return r("il2cpp_gc_is_disabled", "bool", []);
        },
        get gcIsIncremental() {
            return r("il2cpp_gc_is_incremental", "bool", []);
        },
        get gcSetMaxTimeSlice() {
            return r("il2cpp_gc_set_max_time_slice_ns", "void", ["int64"]);
        },
        get gcStartIncrementalCollection() {
            return r("il2cpp_gc_start_incremental_collection", "void", []);
        },
        get gcStartWorld() {
            return r("il2cpp_start_gc_world", "void", []);
        },
        get gcStopWorld() {
            return r("il2cpp_stop_gc_world", "void", []);
        },
        get getCorlib() {
            return r("il2cpp_get_corlib", "pointer", []);
        },
        get imageGetAssembly() {
            return r("il2cpp_image_get_assembly", "pointer", ["pointer"]);
        },
        get imageGetClass() {
            return r("il2cpp_image_get_class", "pointer", ["pointer", "uint"]);
        },
        get imageGetClassCount() {
            return r("il2cpp_image_get_class_count", "uint32", ["pointer"]);
        },
        get imageGetName() {
            return r("il2cpp_image_get_name", "pointer", ["pointer"]);
        },
        get initialize() {
            return r("il2cpp_init", "void", ["pointer"]);
        },
        get livenessAllocateStruct() {
            return r("il2cpp_unity_liveness_allocate_struct", "pointer", ["pointer", "int", "pointer", "pointer", "pointer"]);
        },
        get livenessCalculationBegin() {
            return r("il2cpp_unity_liveness_calculation_begin", "pointer", ["pointer", "int", "pointer", "pointer", "pointer", "pointer"]);
        },
        get livenessCalculationEnd() {
            return r("il2cpp_unity_liveness_calculation_end", "void", ["pointer"]);
        },
        get livenessCalculationFromStatics() {
            return r("il2cpp_unity_liveness_calculation_from_statics", "void", ["pointer"]);
        },
        get livenessFinalize() {
            return r("il2cpp_unity_liveness_finalize", "void", ["pointer"]);
        },
        get livenessFreeStruct() {
            return r("il2cpp_unity_liveness_free_struct", "void", ["pointer"]);
        },
        get memorySnapshotCapture() {
            return r("il2cpp_capture_memory_snapshot", "pointer", []);
        },
        get memorySnapshotFree() {
            return r("il2cpp_free_captured_memory_snapshot", "void", ["pointer"]);
        },
        get memorySnapshotGetClasses() {
            return r("il2cpp_memory_snapshot_get_classes", "pointer", ["pointer", "pointer"]);
        },
        get memorySnapshotGetObjects() {
            return r("il2cpp_memory_snapshot_get_objects", "pointer", ["pointer", "pointer"]);
        },
        get methodGetClass() {
            return r("il2cpp_method_get_class", "pointer", ["pointer"]);
        },
        get methodGetFlags() {
            return r("il2cpp_method_get_flags", "uint32", ["pointer", "pointer"]);
        },
        get methodGetName() {
            return r("il2cpp_method_get_name", "pointer", ["pointer"]);
        },
        get methodGetObject() {
            return r("il2cpp_method_get_object", "pointer", ["pointer", "pointer"]);
        },
        get methodGetParameterCount() {
            return r("il2cpp_method_get_param_count", "uint8", ["pointer"]);
        },
        get methodGetParameterName() {
            return r("il2cpp_method_get_param_name", "pointer", ["pointer", "uint32"]);
        },
        get methodGetParameters() {
            return r("il2cpp_method_get_parameters", "pointer", ["pointer", "pointer"]);
        },
        get methodGetParameterType() {
            return r("il2cpp_method_get_param", "pointer", ["pointer", "uint32"]);
        },
        get methodGetReturnType() {
            return r("il2cpp_method_get_return_type", "pointer", ["pointer"]);
        },
        get methodIsGeneric() {
            return r("il2cpp_method_is_generic", "bool", ["pointer"]);
        },
        get methodIsInflated() {
            return r("il2cpp_method_is_inflated", "bool", ["pointer"]);
        },
        get methodIsInstance() {
            return r("il2cpp_method_is_instance", "bool", ["pointer"]);
        },
        get monitorEnter() {
            return r("il2cpp_monitor_enter", "void", ["pointer"]);
        },
        get monitorExit() {
            return r("il2cpp_monitor_exit", "void", ["pointer"]);
        },
        get monitorPulse() {
            return r("il2cpp_monitor_pulse", "void", ["pointer"]);
        },
        get monitorPulseAll() {
            return r("il2cpp_monitor_pulse_all", "void", ["pointer"]);
        },
        get monitorTryEnter() {
            return r("il2cpp_monitor_try_enter", "bool", ["pointer", "uint32"]);
        },
        get monitorTryWait() {
            return r("il2cpp_monitor_try_wait", "bool", ["pointer", "uint32"]);
        },
        get monitorWait() {
            return r("il2cpp_monitor_wait", "void", ["pointer"]);
        },
        get objectGetClass() {
            return r("il2cpp_object_get_class", "pointer", ["pointer"]);
        },
        get objectGetVirtualMethod() {
            return r("il2cpp_object_get_virtual_method", "pointer", ["pointer", "pointer"]);
        },
        get objectInitialize() {
            return r("il2cpp_runtime_object_init_exception", "void", ["pointer", "pointer"]);
        },
        get objectNew() {
            return r("il2cpp_object_new", "pointer", ["pointer"]);
        },
        get objectGetSize() {
            return r("il2cpp_object_get_size", "uint32", ["pointer"]);
        },
        get objectUnbox() {
            return r("il2cpp_object_unbox", "pointer", ["pointer"]);
        },
        get resolveInternalCall() {
            return r("il2cpp_resolve_icall", "pointer", ["pointer"]);
        },
        get stringGetChars() {
            return r("il2cpp_string_chars", "pointer", ["pointer"]);
        },
        get stringGetLength() {
            return r("il2cpp_string_length", "int32", ["pointer"]);
        },
        get stringNew() {
            return r("il2cpp_string_new", "pointer", ["pointer"]);
        },
        get valueTypeBox() {
            return r("il2cpp_value_box", "pointer", ["pointer", "pointer"]);
        },
        get threadAttach() {
            return r("il2cpp_thread_attach", "pointer", ["pointer"]);
        },
        get threadDetach() {
            return r("il2cpp_thread_detach", "void", ["pointer"]);
        },
        get threadGetAttachedThreads() {
            return r("il2cpp_thread_get_all_attached_threads", "pointer", ["pointer"]);
        },
        get threadGetCurrent() {
            return r("il2cpp_thread_current", "pointer", []);
        },
        get threadIsVm() {
            return r("il2cpp_is_vm_thread", "bool", ["pointer"]);
        },
        get typeGetClass() {
            return r("il2cpp_class_from_type", "pointer", ["pointer"]);
        },
        get typeGetName() {
            return r("il2cpp_type_get_name", "pointer", ["pointer"]);
        },
        get typeGetObject() {
            return r("il2cpp_type_get_object", "pointer", ["pointer"]);
        },
        get typeGetTypeEnum() {
            return r("il2cpp_type_get_type", "int", ["pointer"]);
        }
    };
    decorate(Il2Cpp.api, lazy);
    getter(Il2Cpp, "memorySnapshotApi", () => new CModule("#include <stdint.h>\n#include <string.h>\n\ntypedef struct Il2CppManagedMemorySnapshot Il2CppManagedMemorySnapshot;\ntypedef struct Il2CppMetadataType Il2CppMetadataType;\n\nstruct Il2CppManagedMemorySnapshot\n{\n  struct Il2CppManagedHeap\n  {\n    uint32_t section_count;\n    void * sections;\n  } heap;\n  struct Il2CppStacks\n  {\n    uint32_t stack_count;\n    void * stacks;\n  } stacks;\n  struct Il2CppMetadataSnapshot\n  {\n    uint32_t type_count;\n    Il2CppMetadataType * types;\n  } metadata_snapshot;\n  struct Il2CppGCHandles\n  {\n    uint32_t tracked_object_count;\n    void ** pointers_to_objects;\n  } gc_handles;\n  struct Il2CppRuntimeInformation\n  {\n    uint32_t pointer_size;\n    uint32_t object_header_size;\n    uint32_t array_header_size;\n    uint32_t array_bounds_offset_in_header;\n    uint32_t array_size_offset_in_header;\n    uint32_t allocation_granularity;\n  } runtime_information;\n  void * additional_user_information;\n};\n\nstruct Il2CppMetadataType\n{\n  uint32_t flags;\n  void * fields;\n  uint32_t field_count;\n  uint32_t statics_size;\n  uint8_t * statics;\n  uint32_t base_or_element_type_index;\n  char * name;\n  const char * assembly_name;\n  uint64_t type_info_address;\n  uint32_t size;\n};\n\nuintptr_t\nil2cpp_memory_snapshot_get_classes (\n    const Il2CppManagedMemorySnapshot * snapshot, Il2CppMetadataType ** iter)\n{\n  const int zero = 0;\n  const void * null = 0;\n\n  if (iter != NULL && snapshot->metadata_snapshot.type_count > zero)\n  {\n    if (*iter == null)\n    {\n      *iter = snapshot->metadata_snapshot.types;\n      return (uintptr_t) (*iter)->type_info_address;\n    }\n    else\n    {\n      Il2CppMetadataType * metadata_type = *iter + 1;\n\n      if (metadata_type < snapshot->metadata_snapshot.types +\n                              snapshot->metadata_snapshot.type_count)\n      {\n        *iter = metadata_type;\n        return (uintptr_t) (*iter)->type_info_address;\n      }\n    }\n  }\n  return 0;\n}\n\nvoid **\nil2cpp_memory_snapshot_get_objects (\n    const Il2CppManagedMemorySnapshot * snapshot, uint32_t * size)\n{\n  *size = snapshot->gc_handles.tracked_object_count;\n  return snapshot->gc_handles.pointers_to_objects;\n}\n"), lazy);
    function r(exportName, retType, argTypes) {
        const handle = globalThis.IL2CPP_EXPORTS?.[exportName]?.() ?? Il2Cpp.module.findExportByName(exportName) ?? Il2Cpp.memorySnapshotApi[exportName];
        return new NativeFunction(handle ?? raise(`couldn't resolve export ${exportName}`), retType, argTypes);
    }
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /** */
    Il2Cpp.application = {
        /**
         * Gets the data path name of the current application, e.g.
         * `/data/emulated/0/Android/data/com.example.application/files`
         * on Android.
         *
         * **This information is not guaranteed to exist.**
         *
         * ```ts
         * Il2Cpp.perform(() => {
         *     // prints /data/emulated/0/Android/data/com.example.application/files
         *     console.log(Il2Cpp.application.dataPath);
         * });
         * ```
         */
        get dataPath() {
            return unityEngineCall("get_persistentDataPath");
        },
        /**
         * Gets the identifier name of the current application, e.g.
         * `com.example.application` on Android.
         *
         * **This information is not guaranteed to exist.**
         *
         * ```ts
         * Il2Cpp.perform(() => {
         *     // prints com.example.application
         *     console.log(Il2Cpp.application.identifier);
         * });
         * ```
         */
        get identifier() {
            return unityEngineCall("get_identifier") ?? unityEngineCall("get_bundleIdentifier");
        },
        /**
         * Gets the version name of the current application, e.g. `4.12.8`.
         *
         * **This information is not guaranteed to exist.**
         *
         * ```ts
         * Il2Cpp.perform(() => {
         *     // prints 4.12.8
         *     console.log(Il2Cpp.application.version);
         * });
         * ```
         */
        get version() {
            return unityEngineCall("get_version");
        }
    };
    // prettier-ignore
    getter(Il2Cpp, "unityVersion", () => {
        try {
            const unityVersion = globalThis.IL2CPP_UNITY_VERSION ?? unityEngineCall("get_unityVersion");
            if (unityVersion != null) {
                return unityVersion;
            }
        }
        catch (_) {
        }
        const searchPattern = "69 6c 32 63 70 70";
        for (const range of Il2Cpp.module.enumerateRanges("r--").concat(Process.getRangeByAddress(Il2Cpp.module.base))) {
            for (let { address } of Memory.scanSync(range.base, range.size, searchPattern)) {
                while (address.readU8() != 0) {
                    address = address.sub(1);
                }
                const match = UnityVersion.find(address.add(1).readCString());
                if (match != undefined) {
                    return match;
                }
            }
        }
        raise("couldn't determine the Unity version, please specify it manually");
    }, lazy);
    // prettier-ignore
    getter(Il2Cpp, "unityVersionIsBelow201830", () => {
        return UnityVersion.lt(Il2Cpp.unityVersion, "2018.3.0");
    }, lazy);
    // prettier-ignore
    getter(Il2Cpp, "unityVersionIsBelow202120", () => {
        return UnityVersion.lt(Il2Cpp.unityVersion, "2021.2.0");
    }, lazy);
    function unityEngineCall(method) {
        const handle = Il2Cpp.api.resolveInternalCall(Memory.allocUtf8String("UnityEngine.Application::" + method));
        const nativeFunction = new NativeFunction(handle, "pointer", []);
        return nativeFunction.isNull() ? null : new Il2Cpp.String(nativeFunction()).asNullable()?.content ?? null;
    }
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /**
     * Dumps the application, i.e. it creates a dummy `.cs` file that contains
     * all the class, field and method declarations.
     *
     * The dump is very useful when it comes to inspecting the application as
     * you can easily search for succulent members using a simple text search,
     * hence this is typically the very first thing it should be done when
     * working with a new application. \
     * Keep in mind the dump is version, platform and arch dependentend, so
     * it has to be re-genereated if any of these changes.
     *
     * The file is generated in the **target** device, so you might need to
     * pull it to the host device afterwards.
     *
     * Dumping *may* require a file name and a directory path (a place where the
     * application can write to). If not provided, the target path is generated
     * automatically using the information from {@link Il2Cpp.application}.
     *
     * ```ts
     * Il2Cpp.perform(() => {
     *     Il2Cpp.dump();
     * });
     * ```
     *
     * For instance, the dump resembles the following:
     * ```
     * class Mono.DataConverter.PackContext : System.Object
     * {
     *     System.Byte[] buffer; // 0x10
     *     System.Int32 next; // 0x18
     *     System.String description; // 0x20
     *     System.Int32 i; // 0x28
     *     Mono.DataConverter conv; // 0x30
     *     System.Int32 repeat; // 0x38
     *     System.Int32 align; // 0x3c
     *
     *     System.Void Add(System.Byte[] group); // 0x012ef4f0
     *     System.Byte[] Get(); // 0x012ef6ec
     *     System.Void .ctor(); // 0x012ef78c
     *   }
     * ```
     */
    function dump(fileName, path) {
        fileName = fileName ?? `${Il2Cpp.application.identifier ?? "unknown"}_${Il2Cpp.application.version ?? "unknown"}.cs`;
        const destination = `${path ?? Il2Cpp.application.dataPath}/${fileName}`;
        const file = new File(destination, "w");
        for (const assembly of Il2Cpp.domain.assemblies) {
            inform(`dumping ${assembly.name}...`);
            for (const klass of assembly.image.classes) {
                file.write(`${klass}\n\n`);
            }
        }
        file.flush();
        file.close();
        ok(`dump saved to ${destination}`);
    }
    Il2Cpp.dump = dump;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /**
     * Installs a listener to track any thrown (unrecoverable) C# exception. \
     * This may be useful when incurring in `abort was called` errors.
     *
     * By default, it only tracks exceptions that were thrown by the *caller*
     * thread.
     *
     * **It may not work for every platform.**
     *
     * ```ts
     * Il2Cpp.perform(() => {
     *     Il2Cpp.installExceptionListener("all");
     *
     *     // rest of the code
     * });
     * ```
     *
     * For instance, it may print something along:
     * ```
     * System.NullReferenceException: Object reference not set to an instance of an object.
     *   at AddressableLoadWrapper+<LoadGameObject>d__3[T].MoveNext () [0x00000] in <00000000000000000000000000000000>:0
     *   at UnityEngine.SetupCoroutine.InvokeMoveNext (System.Collections.IEnumerator enumerator, System.IntPtr returnValueAddress) [0x00000] in <00000000000000000000000000000000>:0
     * ```
     */
    function installExceptionListener(targetThread = "current") {
        const currentThread = Il2Cpp.api.threadGetCurrent();
        return Interceptor.attach(Il2Cpp.module.getExportByName("__cxa_throw"), function (args) {
            if (targetThread == "current" && !Il2Cpp.api.threadGetCurrent().equals(currentThread)) {
                return;
            }
            inform(new Il2Cpp.Object(args[0].readPointer()));
        });
    }
    Il2Cpp.installExceptionListener = installExceptionListener;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /**
     * Creates a filter to include elements whose type can be assigned to a
     * variable of the given class. \
     * It relies on {@link Il2Cpp.Class.isAssignableFrom}.
     *
     * ```ts
     * const IComparable = Il2Cpp.corlib.class("System.IComparable");
     *
     * const objects = [
     *     Il2Cpp.corlib.class("System.Object").new(),
     *     Il2Cpp.corlib.class("System.String").new()
     * ];
     *
     * const comparables = objects.filter(Il2Cpp.is(IComparable));
     * ```
     */
    function is(klass) {
        return (element) => {
            if (element instanceof Il2Cpp.Class) {
                return klass.isAssignableFrom(element);
            }
            else {
                return klass.isAssignableFrom(element.class);
            }
        };
    }
    Il2Cpp.is = is;
    /**
     * Creates a filter to include elements whose type can be corresponds to
     * the given class. \
     * It compares the native handle of the element classes.
     *
     * ```ts
     * const String = Il2Cpp.corlib.class("System.String");
     *
     * const objects = [
     *     Il2Cpp.corlib.class("System.Object").new(),
     *     Il2Cpp.corlib.class("System.String").new()
     * ];
     *
     * const strings = objects.filter(Il2Cpp.isExactly(String));
     * ```
     */
    function isExactly(klass) {
        return (element) => {
            if (element instanceof Il2Cpp.Class) {
                return element.equals(klass);
            }
            else {
                return element.class.equals(klass);
            }
        };
    }
    Il2Cpp.isExactly = isExactly;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /**
     * The object literal to interacts with the garbage collector.
     */
    Il2Cpp.gc = {
        /**
         * Gets the heap size in bytes.
         */
        get heapSize() {
            return Il2Cpp.api.gcGetHeapSize();
        },
        /**
         * Determines whether the garbage collector is enabled.
         */
        get isEnabled() {
            return !Il2Cpp.api.gcIsDisabled();
        },
        /**
         * Determines whether the garbage collector is incremental
         * ([source](https://docs.unity3d.com/Manual/performance-incremental-garbage-collection.html)).
         */
        get isIncremental() {
            return !!Il2Cpp.api.gcIsIncremental();
        },
        /**
         * Gets the number of nanoseconds the garbage collector can spend in a
         * collection step.
         */
        get maxTimeSlice() {
            return Il2Cpp.api.gcGetMaxTimeSlice();
        },
        /**
         * Gets the used heap size in bytes.
         */
        get usedHeapSize() {
            return Il2Cpp.api.gcGetUsedSize();
        },
        /**
         * Enables or disables the garbage collector.
         */
        set isEnabled(value) {
            value ? Il2Cpp.api.gcEnable() : Il2Cpp.api.gcDisable();
        },
        /**
         *  Sets the number of nanoseconds the garbage collector can spend in
         * a collection step.
         */
        set maxTimeSlice(nanoseconds) {
            Il2Cpp.api.gcSetMaxTimeSlice(nanoseconds);
        },
        /**
         * Returns the heap allocated objects of the specified class. \
         * This variant reads GC descriptors.
         */
        choose(klass) {
            const matches = [];
            const callback = (objects, size) => {
                for (let i = 0; i < size; i++) {
                    matches.push(new Il2Cpp.Object(objects.add(i * Process.pointerSize).readPointer()));
                }
            };
            const chooseCallback = new NativeCallback(callback, "void", ["pointer", "int", "pointer"]);
            if (Il2Cpp.unityVersionIsBelow202120) {
                const onWorld = new NativeCallback(() => { }, "void", []);
                const state = Il2Cpp.api.livenessCalculationBegin(klass, 0, chooseCallback, NULL, onWorld, onWorld);
                Il2Cpp.api.livenessCalculationFromStatics(state);
                Il2Cpp.api.livenessCalculationEnd(state);
            }
            else {
                const realloc = (handle, size) => {
                    if (!handle.isNull() && size.compare(0) == 0) {
                        Il2Cpp.free(handle);
                        return NULL;
                    }
                    else {
                        return Il2Cpp.alloc(size);
                    }
                };
                const reallocCallback = new NativeCallback(realloc, "pointer", ["pointer", "size_t", "pointer"]);
                this.stopWorld();
                const state = Il2Cpp.api.livenessAllocateStruct(klass, 0, chooseCallback, NULL, reallocCallback);
                Il2Cpp.api.livenessCalculationFromStatics(state);
                Il2Cpp.api.livenessFinalize(state);
                this.startWorld();
                Il2Cpp.api.livenessFreeStruct(state);
            }
            return matches;
        },
        /**
         * Forces a garbage collection of the specified generation.
         */
        collect(generation) {
            Il2Cpp.api.gcCollect(generation < 0 ? 0 : generation > 2 ? 2 : generation);
        },
        /**
         * Forces a garbage collection.
         */
        collectALittle() {
            Il2Cpp.api.gcCollectALittle();
        },
        /**
         *  Resumes all the previously stopped threads.
         */
        startWorld() {
            return Il2Cpp.api.gcStartWorld();
        },
        /**
         * Performs an incremental garbage collection.
         */
        startIncrementalCollection() {
            return Il2Cpp.api.gcStartIncrementalCollection();
        },
        /**
         * Stops all threads which may access the garbage collected heap, other
         * than the caller.
         */
        stopWorld() {
            return Il2Cpp.api.gcStopWorld();
        }
    };
})(Il2Cpp || (Il2Cpp = {}));
/** @internal */
var Android;
(function (Android) {
    // prettier-ignore
    getter(Android, "apiLevel", () => {
        const value = getProperty("ro.build.version.sdk");
        return value ? parseInt(value) : null;
    }, lazy);
    function getProperty(name) {
        const handle = Module.findExportByName("libc.so", "__system_property_get");
        if (handle) {
            const __system_property_get = new NativeFunction(handle, "void", ["pointer", "pointer"]);
            const value = Memory.alloc(92).writePointer(NULL);
            __system_property_get(Memory.allocUtf8String(name), value);
            return value.readCString() ?? undefined;
        }
    }
})(Android || (Android = {}));
/** @internal */
function raise(message) {
    const error = new Error(`\x1b[0m${message}`);
    error.name = `\x1b[0m\x1b[38;5;9mil2cpp\x1b[0m`;
    error.stack = error.stack
        ?.replace(/^Error/, error.name)
        ?.replace(/\n    at (.+) \((.+):(.+)\)/, "\x1b[3m\x1b[2m")
        ?.concat("\x1B[0m");
    throw error;
}
/** @internal */
function warn(message) {
    globalThis.console.log(`\x1b[38;5;11mil2cpp\x1b[0m: ${message}`);
}
/** @internal */
function ok(message) {
    globalThis.console.log(`\x1b[38;5;10mil2cpp\x1b[0m: ${message}`);
}
/** @internal */
function inform(message) {
    globalThis.console.log(`\x1b[38;5;12mil2cpp\x1b[0m: ${message}`);
}
/** @internal */
function decorate(target, decorator, descriptors = Object.getOwnPropertyDescriptors(target)) {
    for (const key in descriptors) {
        descriptors[key] = decorator(target, key, descriptors[key]);
    }
    Object.defineProperties(target, descriptors);
    return target;
}
/** @internal */
function getter(target, key, get, decorator) {
    globalThis.Object.defineProperty(target, key, decorator?.(target, key, { get, configurable: true }) ?? { get, configurable: true });
}
/** @internal */
function lazy(_, propertyKey, descriptor) {
    const getter = descriptor.get;
    if (!getter) {
        throw new Error("@lazy can only be applied to getter accessors");
    }
    descriptor.get = function () {
        const value = getter.call(this);
        Object.defineProperty(this, propertyKey, {
            value,
            configurable: descriptor.configurable,
            enumerable: descriptor.enumerable,
            writable: false
        });
        return value;
    };
    return descriptor;
}
/** Scaffold class. */
class NativeStruct {
    handle;
    constructor(handleOrWrapper) {
        if (handleOrWrapper instanceof NativePointer) {
            this.handle = handleOrWrapper;
        }
        else {
            this.handle = handleOrWrapper.handle;
        }
    }
    equals(other) {
        return this.handle.equals(other.handle);
    }
    isNull() {
        return this.handle.isNull();
    }
    asNullable() {
        return this.isNull() ? null : this;
    }
}
/** @internal */
function forModule(...moduleNames) {
    function find(moduleName, name, readString = _ => _.readUtf8String()) {
        const handle = Module.findExportByName(moduleName, name) ?? NULL;
        if (!handle.isNull()) {
            return { handle, readString };
        }
    }
    return new Promise(resolve => {
        for (const moduleName of moduleNames) {
            const module = Process.findModuleByName(moduleName);
            if (module != null) {
                resolve(module);
                return;
            }
        }
        let targets = [];
        switch (Process.platform) {
            case "linux":
                if (Android.apiLevel == null) {
                    targets = [find(null, "dlopen")];
                    break;
                }
                // A5: device reboot, can't hook symbols
                // A6, A7: __dl_open
                // A8, A8.1: __dl__Z8__dlopenPKciPKv
                // A9, A10, A12, A13: __dl___loader_dlopen
                targets = (Process.findModuleByName("linker64") ?? Process.getModuleByName("linker"))
                    .enumerateSymbols()
                    .filter(_ => ["__dl___loader_dlopen", "__dl__Z8__dlopenPKciPKv", "__dl_open"].includes(_.name))
                    .map(_ => ({ handle: _.address, readString: _ => _.readCString() }));
                break;
            case "darwin":
                targets = [find("libdyld.dylib", "dlopen")];
                break;
            case "windows":
                targets = [
                    find("kernel32.dll", "LoadLibraryW", _ => _.readUtf16String()),
                    find("kernel32.dll", "LoadLibraryExW", _ => _.readUtf16String()),
                    find("kernel32.dll", "LoadLibraryA", _ => _.readAnsiString()),
                    find("kernel32.dll", "LoadLibraryExA", _ => _.readAnsiString())
                ];
                break;
        }
        targets = targets.filter(_ => _);
        if (targets.length == 0) {
            raise(`there are no targets to hook the loading of \x1b[3m${moduleNames}\x1b[0m, please file a bug`);
        }
        const timeout = setTimeout(() => {
            for (const moduleName of moduleNames) {
                const module = Process.findModuleByName(moduleName);
                if (module != null) {
                    warn(`\x1b[3m${module.name}\x1b[0m has been loaded, but such event hasn't been detected - please file a bug`);
                    clearTimeout(timeout);
                    interceptors.forEach(_ => _.detach());
                    resolve(module);
                    return;
                }
            }
            warn(`10 seconds have passed and \x1b[3m${moduleNames}\x1b[0m has not been loaded yet, is the app running?`);
        }, 10000);
        const interceptors = targets.map(_ => Interceptor.attach(_.handle, {
            onEnter(args) {
                this.modulePath = _.readString(args[0]) ?? "";
            },
            onLeave(_) {
                for (const moduleName of moduleNames) {
                    if (this.modulePath.endsWith(moduleName)) {
                        // Adding a fallback in case Frida cannot find the module by its full path
                        // https://github.com/vfsfitvnm/frida-il2cpp-bridge/issues/547
                        const module = Process.findModuleByName(this.modulePath) ?? Process.findModuleByName(moduleName);
                        if (module != null) {
                            setImmediate(() => {
                                clearTimeout(timeout);
                                interceptors.forEach(_ => _.detach());
                            });
                            resolve(module);
                            break;
                        }
                    }
                }
            }
        }));
    });
}
NativePointer.prototype.offsetOf = function (condition, depth) {
    depth ??= 512;
    for (let i = 0; depth > 0 ? i < depth : i < -depth; i++) {
        if (condition(depth > 0 ? this.add(i) : this.sub(i))) {
            return i;
        }
    }
    return null;
};
/** @internal */
function readNativeIterator(block) {
    const array = [];
    const iterator = Memory.alloc(Process.pointerSize);
    let handle = block(iterator);
    while (!handle.isNull()) {
        array.push(handle);
        handle = block(iterator);
    }
    return array;
}
/** @internal */
function readNativeList(block) {
    const lengthPointer = Memory.alloc(Process.pointerSize);
    const startPointer = block(lengthPointer);
    if (startPointer.isNull()) {
        return [];
    }
    const array = new Array(lengthPointer.readInt());
    for (let i = 0; i < array.length; i++) {
        array[i] = startPointer.add(i * Process.pointerSize).readPointer();
    }
    return array;
}
/** @internal */
function recycle(Class) {
    return new Proxy(Class, {
        cache: new Map(),
        construct(Target, argArray) {
            const handle = argArray[0].toUInt32();
            if (!this.cache.has(handle)) {
                this.cache.set(handle, new Target(argArray[0]));
            }
            return this.cache.get(handle);
        }
    });
}
/** @internal */
var UnityVersion;
(function (UnityVersion) {
    const pattern = /(20\d{2}|\d)\.(\d)\.(\d{1,2})(?:[abcfp]|rc){0,2}\d?/;
    function find(string) {
        return string?.match(pattern)?.[0];
    }
    UnityVersion.find = find;
    function gte(a, b) {
        return compare(a, b) >= 0;
    }
    UnityVersion.gte = gte;
    function lt(a, b) {
        return compare(a, b) < 0;
    }
    UnityVersion.lt = lt;
    function compare(a, b) {
        const aMatches = a.match(pattern);
        const bMatches = b.match(pattern);
        for (let i = 1; i <= 3; i++) {
            const a = Number(aMatches?.[i] ?? -1);
            const b = Number(bMatches?.[i] ?? -1);
            if (a > b)
                return 1;
            else if (a < b)
                return -1;
        }
        return 0;
    }
})(UnityVersion || (UnityVersion = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /**
     * Allocates the given amount of bytes - it's equivalent to C's `malloc`. \
     * The allocated memory should be freed manually.
     */
    function alloc(size = Process.pointerSize) {
        return Il2Cpp.api.alloc(size);
    }
    Il2Cpp.alloc = alloc;
    /**
     * Frees a previously allocated memory using {@link Il2Cpp.alloc} - it's
     *  equivalent to C's `free`..
     *
     * ```ts
     * const handle = Il2Cpp.alloc(64);
     *
     * // ...
     *
     * Il2Cpp.free(handle);
     * ```
     */
    function free(pointer) {
        return Il2Cpp.api.free(pointer);
    }
    Il2Cpp.free = free;
    /** @internal */
    function read(pointer, type) {
        switch (type.typeEnum) {
            case Il2Cpp.Type.enum.boolean:
                return !!pointer.readS8();
            case Il2Cpp.Type.enum.byte:
                return pointer.readS8();
            case Il2Cpp.Type.enum.unsignedByte:
                return pointer.readU8();
            case Il2Cpp.Type.enum.short:
                return pointer.readS16();
            case Il2Cpp.Type.enum.unsignedShort:
                return pointer.readU16();
            case Il2Cpp.Type.enum.int:
                return pointer.readS32();
            case Il2Cpp.Type.enum.unsignedInt:
                return pointer.readU32();
            case Il2Cpp.Type.enum.char:
                return pointer.readU16();
            case Il2Cpp.Type.enum.long:
                return pointer.readS64();
            case Il2Cpp.Type.enum.unsignedLong:
                return pointer.readU64();
            case Il2Cpp.Type.enum.float:
                return pointer.readFloat();
            case Il2Cpp.Type.enum.double:
                return pointer.readDouble();
            case Il2Cpp.Type.enum.nativePointer:
            case Il2Cpp.Type.enum.unsignedNativePointer:
                return pointer.readPointer();
            case Il2Cpp.Type.enum.pointer:
                return new Il2Cpp.Pointer(pointer.readPointer(), type.class.baseType);
            case Il2Cpp.Type.enum.valueType:
                return new Il2Cpp.ValueType(pointer, type);
            case Il2Cpp.Type.enum.object:
            case Il2Cpp.Type.enum.class:
                return new Il2Cpp.Object(pointer.readPointer());
            case Il2Cpp.Type.enum.genericInstance:
                return type.class.isValueType ? new Il2Cpp.ValueType(pointer, type) : new Il2Cpp.Object(pointer.readPointer());
            case Il2Cpp.Type.enum.string:
                return new Il2Cpp.String(pointer.readPointer());
            case Il2Cpp.Type.enum.array:
            case Il2Cpp.Type.enum.multidimensionalArray:
                return new Il2Cpp.Array(pointer.readPointer());
        }
        raise(`couldn't read the value from ${pointer} using an unhandled or unknown type ${type.name} (${type.typeEnum}), please file an issue`);
    }
    Il2Cpp.read = read;
    /** @internal */
    function write(pointer, value, type) {
        switch (type.typeEnum) {
            case Il2Cpp.Type.enum.boolean:
                return pointer.writeS8(+value);
            case Il2Cpp.Type.enum.byte:
                return pointer.writeS8(value);
            case Il2Cpp.Type.enum.unsignedByte:
                return pointer.writeU8(value);
            case Il2Cpp.Type.enum.short:
                return pointer.writeS16(value);
            case Il2Cpp.Type.enum.unsignedShort:
                return pointer.writeU16(value);
            case Il2Cpp.Type.enum.int:
                return pointer.writeS32(value);
            case Il2Cpp.Type.enum.unsignedInt:
                return pointer.writeU32(value);
            case Il2Cpp.Type.enum.char:
                return pointer.writeU16(value);
            case Il2Cpp.Type.enum.long:
                return pointer.writeS64(value);
            case Il2Cpp.Type.enum.unsignedLong:
                return pointer.writeU64(value);
            case Il2Cpp.Type.enum.float:
                return pointer.writeFloat(value);
            case Il2Cpp.Type.enum.double:
                return pointer.writeDouble(value);
            case Il2Cpp.Type.enum.nativePointer:
            case Il2Cpp.Type.enum.unsignedNativePointer:
            case Il2Cpp.Type.enum.pointer:
            case Il2Cpp.Type.enum.string:
            case Il2Cpp.Type.enum.array:
            case Il2Cpp.Type.enum.multidimensionalArray:
                return pointer.writePointer(value);
            case Il2Cpp.Type.enum.valueType:
                return Memory.copy(pointer, value, type.class.valueTypeSize), pointer;
            case Il2Cpp.Type.enum.object:
            case Il2Cpp.Type.enum.class:
            case Il2Cpp.Type.enum.genericInstance:
                return value instanceof Il2Cpp.ValueType ? (Memory.copy(pointer, value, type.class.valueTypeSize), pointer) : pointer.writePointer(value);
        }
        raise(`couldn't write value ${value} to ${pointer} using an unhandled or unknown type ${type.name} (${type.typeEnum}), please file an issue`);
    }
    Il2Cpp.write = write;
    /** @internal */
    function fromFridaValue(value, type) {
        if (globalThis.Array.isArray(value)) {
            const handle = Memory.alloc(type.class.valueTypeSize);
            const fields = type.class.fields.filter(_ => !_.isStatic);
            for (let i = 0; i < fields.length; i++) {
                const convertedValue = fromFridaValue(value[i], fields[i].type);
                write(handle.add(fields[i].offset).sub(Il2Cpp.Object.headerSize), convertedValue, fields[i].type);
            }
            return new Il2Cpp.ValueType(handle, type);
        }
        else if (value instanceof NativePointer) {
            if (type.isByReference) {
                return new Il2Cpp.Reference(value, type);
            }
            switch (type.typeEnum) {
                case Il2Cpp.Type.enum.pointer:
                    return new Il2Cpp.Pointer(value, type.class.baseType);
                case Il2Cpp.Type.enum.string:
                    return new Il2Cpp.String(value);
                case Il2Cpp.Type.enum.class:
                case Il2Cpp.Type.enum.genericInstance:
                case Il2Cpp.Type.enum.object:
                    return new Il2Cpp.Object(value);
                case Il2Cpp.Type.enum.array:
                case Il2Cpp.Type.enum.multidimensionalArray:
                    return new Il2Cpp.Array(value);
                default:
                    return value;
            }
        }
        else if (type.typeEnum == Il2Cpp.Type.enum.boolean) {
            return !!value;
        }
        else if (type.typeEnum == Il2Cpp.Type.enum.valueType && type.class.isEnum) {
            return fromFridaValue([value], type);
        }
        else {
            return value;
        }
    }
    Il2Cpp.fromFridaValue = fromFridaValue;
    /** @internal */
    function toFridaValue(value) {
        if (typeof value == "boolean") {
            return +value;
        }
        else if (value instanceof Il2Cpp.ValueType) {
            if (value.type.class.isEnum) {
                return value.field("value__").value;
            }
            else {
                const _ = value.type.class.fields.filter(_ => !_.isStatic).map(_ => toFridaValue(_.withHolder(value).value));
                return _.length == 0 ? [0] : _;
            }
        }
        else {
            return value;
        }
    }
    Il2Cpp.toFridaValue = toFridaValue;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    getter(Il2Cpp, "module", () => {
        const [moduleName, fallback] = getExpectedModuleNames();
        return Process.findModuleByName(moduleName) ?? Process.getModuleByName(fallback);
    });
    /**
     * @internal
     * Waits for the IL2CPP native library to be loaded and initialized.
     */
    async function initialize(blocking = false) {
        Reflect.defineProperty(Il2Cpp, "module", {
            // prettier-ignore
            value: Process.platform == "darwin"
                ? Process.findModuleByAddress(DebugSymbol.fromName("il2cpp_init").address)
                    ?? await forModule(...getExpectedModuleNames())
                : await forModule(...getExpectedModuleNames())
        });
        // At this point, the IL2CPP native library has been loaded, but we
        // cannot interact with IL2CPP until `il2cpp_init` is done.
        // It looks like `il2cpp_get_corlib` returns NULL only when the
        // initialization is not completed yet.
        if (Il2Cpp.api.getCorlib().isNull()) {
            return await new Promise(resolve => {
                const interceptor = Interceptor.attach(Il2Cpp.api.initialize, {
                    onLeave() {
                        interceptor.detach();
                        blocking ? resolve(true) : setImmediate(() => resolve(false));
                    }
                });
            });
        }
        return false;
    }
    Il2Cpp.initialize = initialize;
    function getExpectedModuleNames() {
        if (globalThis.IL2CPP_MODULE_NAME) {
            return [globalThis.IL2CPP_MODULE_NAME];
        }
        switch (Process.platform) {
            case "linux":
                return [Android.apiLevel ? "libil2cpp.so" : "GameAssembly.so"];
            case "windows":
                return ["GameAssembly.dll"];
            case "darwin":
                return ["UnityFramework", "GameAssembly.dylib"];
        }
        raise(`${Process.platform} is not supported yet`);
    }
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /** Attaches the caller thread to Il2Cpp domain and executes the given block.  */
    async function perform(block, flag = "bind") {
        try {
            const isInMainThread = await Il2Cpp.initialize(flag == "main");
            if (flag == "main" && !isInMainThread) {
                return perform(() => Il2Cpp.mainThread.schedule(block), "free");
            }
            let thread = Il2Cpp.currentThread;
            const isForeignThread = thread == null;
            thread ??= Il2Cpp.domain.attach();
            const result = block();
            if (isForeignThread) {
                if (flag == "free") {
                    thread.detach();
                }
                else if (flag == "bind") {
                    Script.bindWeak(globalThis, () => thread.detach());
                }
            }
            return result instanceof Promise ? await result : result;
        }
        catch (error) {
            Script.nextTick(_ => { throw _; }, error); // prettier-ignore
            return Promise.reject(error);
        }
    }
    Il2Cpp.perform = perform;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Tracer {
        /** @internal */
        #state = {
            depth: 0,
            buffer: [],
            history: new Set(),
            flush: () => {
                if (this.#state.depth == 0) {
                    const message = `\n${this.#state.buffer.join("\n")}\n`;
                    if (this.#verbose) {
                        inform(message);
                    }
                    else {
                        const hash = cyrb53(message);
                        if (!this.#state.history.has(hash)) {
                            this.#state.history.add(hash);
                            inform(message);
                        }
                    }
                    this.#state.buffer.length = 0;
                }
            }
        };
        /** @internal */
        #threadId = Il2Cpp.mainThread.id;
        /** @internal */
        #verbose = false;
        /** @internal */
        #applier;
        /** @internal */
        #targets = [];
        /** @internal */
        #domain;
        /** @internal */
        #assemblies;
        /** @internal */
        #classes;
        /** @internal */
        #methods;
        /** @internal */
        #assemblyFilter;
        /** @internal */
        #classFilter;
        /** @internal */
        #methodFilter;
        /** @internal */
        #parameterFilter;
        constructor(applier) {
            this.#applier = applier;
        }
        /** */
        thread(thread) {
            this.#threadId = thread.id;
            return this;
        }
        /** Determines whether print duplicate logs. */
        verbose(value) {
            this.#verbose = value;
            return this;
        }
        /** Sets the application domain as the place where to find the target methods. */
        domain() {
            this.#domain = Il2Cpp.domain;
            return this;
        }
        /** Sets the passed `assemblies` as the place where to find the target methods. */
        assemblies(...assemblies) {
            this.#assemblies = assemblies;
            return this;
        }
        /** Sets the passed `classes` as the place where to find the target methods. */
        classes(...classes) {
            this.#classes = classes;
            return this;
        }
        /** Sets the passed `methods` as the target methods. */
        methods(...methods) {
            this.#methods = methods;
            return this;
        }
        /** Filters the assemblies where to find the target methods. */
        filterAssemblies(filter) {
            this.#assemblyFilter = filter;
            return this;
        }
        /** Filters the classes where to find the target methods. */
        filterClasses(filter) {
            this.#classFilter = filter;
            return this;
        }
        /** Filters the target methods. */
        filterMethods(filter) {
            this.#methodFilter = filter;
            return this;
        }
        /** Filters the target methods. */
        filterParameters(filter) {
            this.#parameterFilter = filter;
            return this;
        }
        /** Commits the current changes by finding the target methods. */
        and() {
            const filterMethod = (method) => {
                if (this.#parameterFilter == undefined) {
                    this.#targets.push(method);
                    return;
                }
                for (const parameter of method.parameters) {
                    if (this.#parameterFilter(parameter)) {
                        this.#targets.push(method);
                        break;
                    }
                }
            };
            const filterMethods = (values) => {
                for (const method of values) {
                    filterMethod(method);
                }
            };
            const filterClass = (klass) => {
                if (this.#methodFilter == undefined) {
                    filterMethods(klass.methods);
                    return;
                }
                for (const method of klass.methods) {
                    if (this.#methodFilter(method)) {
                        filterMethod(method);
                    }
                }
            };
            const filterClasses = (values) => {
                for (const klass of values) {
                    filterClass(klass);
                }
            };
            const filterAssembly = (assembly) => {
                if (this.#classFilter == undefined) {
                    filterClasses(assembly.image.classes);
                    return;
                }
                for (const klass of assembly.image.classes) {
                    if (this.#classFilter(klass)) {
                        filterClass(klass);
                    }
                }
            };
            const filterAssemblies = (assemblies) => {
                for (const assembly of assemblies) {
                    filterAssembly(assembly);
                }
            };
            const filterDomain = (domain) => {
                if (this.#assemblyFilter == undefined) {
                    filterAssemblies(domain.assemblies);
                    return;
                }
                for (const assembly of domain.assemblies) {
                    if (this.#assemblyFilter(assembly)) {
                        filterAssembly(assembly);
                    }
                }
            };
            this.#methods
                ? filterMethods(this.#methods)
                : this.#classes
                    ? filterClasses(this.#classes)
                    : this.#assemblies
                        ? filterAssemblies(this.#assemblies)
                        : this.#domain
                            ? filterDomain(this.#domain)
                            : undefined;
            this.#assemblies = undefined;
            this.#classes = undefined;
            this.#methods = undefined;
            this.#assemblyFilter = undefined;
            this.#classFilter = undefined;
            this.#methodFilter = undefined;
            this.#parameterFilter = undefined;
            return this;
        }
        /** Starts tracing. */
        attach() {
            for (const target of this.#targets) {
                if (!target.virtualAddress.isNull()) {
                    try {
                        this.#applier(target, this.#state, this.#threadId);
                    }
                    catch (e) {
                        switch (e.message) {
                            case /unable to intercept function at \w+; please file a bug/.exec(e.message)?.input:
                            case "already replaced this function":
                                break;
                            default:
                                throw e;
                        }
                    }
                }
            }
        }
    }
    Il2Cpp.Tracer = Tracer;
    /** */
    function trace(parameters = false) {
        const applier = () => (method, state, threadId) => {
            const paddedVirtualAddress = method.relativeVirtualAddress.toString(16).padStart(8, "0");
            Interceptor.attach(method.virtualAddress, {
                onEnter() {
                    if (this.threadId == threadId) {
                        // prettier-ignore
                        state.buffer.push(`\x1b[2m0x${paddedVirtualAddress}\x1b[0m ${`│ `.repeat(state.depth++)}┌─\x1b[35m${method.class.type.name}::\x1b[1m${method.name}\x1b[0m\x1b[0m`);
                    }
                },
                onLeave() {
                    if (this.threadId == threadId) {
                        // prettier-ignore
                        state.buffer.push(`\x1b[2m0x${paddedVirtualAddress}\x1b[0m ${`│ `.repeat(--state.depth)}└─\x1b[33m${method.class.type.name}::\x1b[1m${method.name}\x1b[0m\x1b[0m`);
                        state.flush();
                    }
                }
            });
        };
        const applierWithParameters = () => (method, state, threadId) => {
            const paddedVirtualAddress = method.relativeVirtualAddress.toString(16).padStart(8, "0");
            const startIndex = +!method.isStatic | +Il2Cpp.unityVersionIsBelow201830;
            const callback = function (...args) {
                if (this.threadId == threadId) {
                    const thisParameter = method.isStatic ? undefined : new Il2Cpp.Parameter("this", -1, method.class.type);
                    const parameters = thisParameter ? [thisParameter].concat(method.parameters) : method.parameters;
                    // prettier-ignore
                    state.buffer.push(`\x1b[2m0x${paddedVirtualAddress}\x1b[0m ${`│ `.repeat(state.depth++)}┌─\x1b[35m${method.class.type.name}::\x1b[1m${method.name}\x1b[0m\x1b[0m(${parameters.map(e => `\x1b[32m${e.name}\x1b[0m = \x1b[31m${Il2Cpp.fromFridaValue(args[e.position + startIndex], e.type)}\x1b[0m`).join(", ")})`);
                }
                const returnValue = method.nativeFunction(...args);
                if (this.threadId == threadId) {
                    // prettier-ignore
                    state.buffer.push(`\x1b[2m0x${paddedVirtualAddress}\x1b[0m ${`│ `.repeat(--state.depth)}└─\x1b[33m${method.class.type.name}::\x1b[1m${method.name}\x1b[0m\x1b[0m${returnValue == undefined ? "" : ` = \x1b[36m${Il2Cpp.fromFridaValue(returnValue, method.returnType)}`}\x1b[0m`);
                    state.flush();
                }
                return returnValue;
            };
            method.revert();
            const nativeCallback = new NativeCallback(callback, method.returnType.fridaAlias, method.fridaSignature);
            Interceptor.replace(method.virtualAddress, nativeCallback);
        };
        return new Il2Cpp.Tracer(parameters ? applierWithParameters() : applier());
    }
    Il2Cpp.trace = trace;
    /** */
    function backtrace(mode) {
        const methods = Il2Cpp.domain.assemblies
            .flatMap(_ => _.image.classes.flatMap(_ => _.methods.filter(_ => !_.virtualAddress.isNull())))
            .sort((_, __) => _.virtualAddress.compare(__.virtualAddress));
        const searchInsert = (target) => {
            let left = 0;
            let right = methods.length - 1;
            while (left <= right) {
                const pivot = Math.floor((left + right) / 2);
                const comparison = methods[pivot].virtualAddress.compare(target);
                if (comparison == 0) {
                    return methods[pivot];
                }
                else if (comparison > 0) {
                    right = pivot - 1;
                }
                else {
                    left = pivot + 1;
                }
            }
            return methods[right];
        };
        const applier = () => (method, state, threadId) => {
            Interceptor.attach(method.virtualAddress, function () {
                if (this.threadId == threadId) {
                    const handles = globalThis.Thread.backtrace(this.context, mode);
                    handles.unshift(method.virtualAddress);
                    for (const handle of handles) {
                        if (handle.compare(Il2Cpp.module.base) > 0 && handle.compare(Il2Cpp.module.base.add(Il2Cpp.module.size)) < 0) {
                            const method = searchInsert(handle);
                            if (method) {
                                const offset = handle.sub(method.virtualAddress);
                                if (offset.compare(0xfff) < 0) {
                                    // prettier-ignore
                                    state.buffer.push(`\x1b[2m0x${method.relativeVirtualAddress.toString(16).padStart(8, "0")}\x1b[0m\x1b[2m+0x${offset.toString(16).padStart(3, `0`)}\x1b[0m ${method.class.type.name}::\x1b[1m${method.name}\x1b[0m`);
                                }
                            }
                        }
                    }
                    state.flush();
                }
            });
        };
        return new Il2Cpp.Tracer(applier());
    }
    Il2Cpp.backtrace = backtrace;
    /** https://stackoverflow.com/a/52171480/16885569 */
    function cyrb53(str) {
        let h1 = 0xdeadbeef;
        let h2 = 0x41c6ce57;
        for (let i = 0, ch; i < str.length; i++) {
            ch = str.charCodeAt(i);
            h1 = Math.imul(h1 ^ ch, 2654435761);
            h2 = Math.imul(h2 ^ ch, 1597334677);
        }
        h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
        h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
        h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
        h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
        return 4294967296 * (2097151 & h2) + (h1 >>> 0);
    }
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Array extends NativeStruct {
        /** Gets the Il2CppArray struct size, possibly equal to `Process.pointerSize * 4`. */
        static get headerSize() {
            return Il2Cpp.corlib.class("System.Array").instanceSize;
        }
        /** @internal Gets a pointer to the first element of the current array. */
        get elements() {
            // We previosly obtained an array whose content is known by calling
            // 'System.String::Split(NULL)' on a known string. However, that
            // method invocation somehow blows things up in Unity 2018.3.0f1.
            const array = Il2Cpp.string("v").object.method("ToCharArray", 0).invoke();
            // prettier-ignore
            const offset = array.handle.offsetOf(_ => _.readS16() == 118) ??
                raise("couldn't find the elements offset in the native array struct");
            // prettier-ignore
            getter(Il2Cpp.Array.prototype, "elements", function () {
                return new Il2Cpp.Pointer(this.handle.add(offset), this.elementType);
            }, lazy);
            return this.elements;
        }
        /** Gets the size of the object encompassed by the current array. */
        get elementSize() {
            return this.elementType.class.arrayElementSize;
        }
        /** Gets the type of the object encompassed by the current array. */
        get elementType() {
            return this.object.class.type.class.baseType;
        }
        /** Gets the total number of elements in all the dimensions of the current array. */
        get length() {
            return Il2Cpp.api.arrayGetLength(this);
        }
        /** Gets the encompassing object of the current array. */
        get object() {
            return new Il2Cpp.Object(this);
        }
        /** Gets the element at the specified index of the current array. */
        get(index) {
            if (index < 0 || index >= this.length) {
                raise(`cannot get element at index ${index} as the array length is ${this.length}`);
            }
            return this.elements.get(index);
        }
        /** Sets the element at the specified index of the current array. */
        set(index, value) {
            if (index < 0 || index >= this.length) {
                raise(`cannot set element at index ${index} as the array length is ${this.length}`);
            }
            this.elements.set(index, value);
        }
        /** */
        toString() {
            return this.isNull() ? "null" : `[${this.elements.read(this.length, 0)}]`;
        }
        /** Iterable. */
        *[Symbol.iterator]() {
            for (let i = 0; i < this.length; i++) {
                yield this.elements.get(i);
            }
        }
    }
    __decorate([
        lazy
    ], Array.prototype, "elementSize", null);
    __decorate([
        lazy
    ], Array.prototype, "elementType", null);
    __decorate([
        lazy
    ], Array.prototype, "length", null);
    __decorate([
        lazy
    ], Array.prototype, "object", null);
    __decorate([
        lazy
    ], Array, "headerSize", null);
    Il2Cpp.Array = Array;
    /** @internal */
    function array(klass, lengthOrElements) {
        const length = typeof lengthOrElements == "number" ? lengthOrElements : lengthOrElements.length;
        const array = new Il2Cpp.Array(Il2Cpp.api.arrayNew(klass, length));
        if (globalThis.Array.isArray(lengthOrElements)) {
            array.elements.write(lengthOrElements);
        }
        return array;
    }
    Il2Cpp.array = array;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    let Assembly = class Assembly extends NativeStruct {
        /** Gets the image of this assembly. */
        get image() {
            let get = function () {
                return new Il2Cpp.Image(Il2Cpp.api.assemblyGetImage(this));
            };
            try {
                Il2Cpp.api.assemblyGetImage;
            }
            catch (_) {
                get = function () {
                    // We need to get the System.Reflection.Module of the current assembly;
                    // System.Reflection.Assembly::GetModulesInternal, for some reason,
                    // throws a NullReferenceExceptionin Unity 5.3.8f1, so we must rely on
                    // System.Type::get_Module instead.
                    // Now we need to get any System.Type of this assembly.
                    // We cannot use System.Reflection.Assembly::GetTypes because it may
                    // return an empty array; hence we use System.Reflection.Assembly::GetType
                    // to retrieve <Module>, a class/type that seems to be always present
                    // (despite being excluded from System.Reflection.Assembly::GetTypes).
                    return new Il2Cpp.Image(this.object
                        .method("GetType", 1)
                        .invoke(Il2Cpp.string("<Module>"))
                        .method("get_Module")
                        .invoke()
                        .field("_impl").value);
                };
            }
            getter(Il2Cpp.Assembly.prototype, "image", get, lazy);
            return this.image;
        }
        /** Gets the name of this assembly. */
        get name() {
            return this.image.name.replace(".dll", "");
        }
        /** Gets the encompassing object of the current assembly. */
        get object() {
            for (const _ of Il2Cpp.domain.object.method("GetAssemblies", 1).invoke(false)) {
                if (_.field("_mono_assembly").value.equals(this)) {
                    return _;
                }
            }
            raise("couldn't find the object of the native assembly struct");
        }
    };
    __decorate([
        lazy
    ], Assembly.prototype, "name", null);
    __decorate([
        lazy
    ], Assembly.prototype, "object", null);
    Assembly = __decorate([
        recycle
    ], Assembly);
    Il2Cpp.Assembly = Assembly;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    let Class = class Class extends NativeStruct {
        /** Gets the actual size of the instance of the current class. */
        get actualInstanceSize() {
            const SystemString = Il2Cpp.corlib.class("System.String");
            // prettier-ignore
            const offset = SystemString.handle.offsetOf(_ => _.readInt() == SystemString.instanceSize - 2)
                ?? raise("couldn't find the actual instance size offset in the native class struct");
            // prettier-ignore
            getter(Il2Cpp.Class.prototype, "actualInstanceSize", function () {
                return this.handle.add(offset).readS32();
            }, lazy);
            return this.actualInstanceSize;
        }
        /** Gets the array class which encompass the current class. */
        get arrayClass() {
            return new Il2Cpp.Class(Il2Cpp.api.classGetArrayClass(this, 1));
        }
        /** Gets the size of the object encompassed by the current array class. */
        get arrayElementSize() {
            return Il2Cpp.api.classGetArrayElementSize(this);
        }
        /** Gets the name of the assembly in which the current class is defined. */
        get assemblyName() {
            return Il2Cpp.api.classGetAssemblyName(this).readUtf8String().replace(".dll", "");
        }
        /** Gets the class that declares the current nested class. */
        get declaringClass() {
            return new Il2Cpp.Class(Il2Cpp.api.classGetDeclaringType(this)).asNullable();
        }
        /** Gets the encompassed type of this array, reference, pointer or enum type. */
        get baseType() {
            return new Il2Cpp.Type(Il2Cpp.api.classGetBaseType(this)).asNullable();
        }
        /** Gets the class of the object encompassed or referred to by the current array, pointer or reference class. */
        get elementClass() {
            return new Il2Cpp.Class(Il2Cpp.api.classGetElementClass(this)).asNullable();
        }
        /** Gets the fields of the current class. */
        get fields() {
            return readNativeIterator(_ => Il2Cpp.api.classGetFields(this, _)).map(_ => new Il2Cpp.Field(_));
        }
        /** Gets the flags of the current class. */
        get flags() {
            return Il2Cpp.api.classGetFlags(this);
        }
        /** Gets the full name (namespace + name) of the current class. */
        get fullName() {
            return this.namespace ? `${this.namespace}.${this.name}` : this.name;
        }
        /** Gets the generics parameters of this generic class. */
        get generics() {
            if (!this.isGeneric && !this.isInflated) {
                return [];
            }
            const types = this.type.object.method("GetGenericArguments").invoke();
            return globalThis.Array.from(types).map(_ => new Il2Cpp.Class(Il2Cpp.api.classFromObject(_)));
        }
        /** Determines whether the GC has tracking references to the current class instances. */
        get hasReferences() {
            return !!Il2Cpp.api.classHasReferences(this);
        }
        /** Determines whether ther current class has a valid static constructor. */
        get hasStaticConstructor() {
            const staticConstructor = this.tryMethod(".cctor");
            return staticConstructor != null && !staticConstructor.virtualAddress.isNull();
        }
        /** Gets the image in which the current class is defined. */
        get image() {
            return new Il2Cpp.Image(Il2Cpp.api.classGetImage(this));
        }
        /** Gets the size of the instance of the current class. */
        get instanceSize() {
            return Il2Cpp.api.classGetInstanceSize(this);
        }
        /** Determines whether the current class is abstract. */
        get isAbstract() {
            return !!Il2Cpp.api.classIsAbstract(this);
        }
        /** Determines whether the current class is blittable. */
        get isBlittable() {
            return !!Il2Cpp.api.classIsBlittable(this);
        }
        /** Determines whether the current class is an enumeration. */
        get isEnum() {
            return !!Il2Cpp.api.classIsEnum(this);
        }
        /** Determines whether the current class is a generic one. */
        get isGeneric() {
            return !!Il2Cpp.api.classIsGeneric(this);
        }
        /** Determines whether the current class is inflated. */
        get isInflated() {
            return !!Il2Cpp.api.classIsInflated(this);
        }
        /** Determines whether the current class is an interface. */
        get isInterface() {
            return !!Il2Cpp.api.classIsInterface(this);
        }
        /** Determines whether the current class is a struct. */
        get isStruct() {
            return this.isValueType && !this.isEnum;
        }
        /** Determines whether the current class is a value type. */
        get isValueType() {
            return !!Il2Cpp.api.classIsValueType(this);
        }
        /** Gets the interfaces implemented or inherited by the current class. */
        get interfaces() {
            return readNativeIterator(_ => Il2Cpp.api.classGetInterfaces(this, _)).map(_ => new Il2Cpp.Class(_));
        }
        /** Gets the methods implemented by the current class. */
        get methods() {
            return readNativeIterator(_ => Il2Cpp.api.classGetMethods(this, _)).map(_ => new Il2Cpp.Method(_));
        }
        /** Gets the name of the current class. */
        get name() {
            return Il2Cpp.api.classGetName(this).readUtf8String();
        }
        /** Gets the namespace of the current class. */
        get namespace() {
            return Il2Cpp.api.classGetNamespace(this).readUtf8String();
        }
        /** Gets the classes nested inside the current class. */
        get nestedClasses() {
            return readNativeIterator(_ => Il2Cpp.api.classGetNestedClasses(this, _)).map(_ => new Il2Cpp.Class(_));
        }
        /** Gets the class from which the current class directly inherits. */
        get parent() {
            return new Il2Cpp.Class(Il2Cpp.api.classGetParent(this)).asNullable();
        }
        /** Gets the rank (number of dimensions) of the current array class. */
        get rank() {
            let rank = 0;
            const name = this.name;
            for (let i = this.name.length - 1; i > 0; i--) {
                const c = name[i];
                if (c == "]")
                    rank++;
                else if (c == "[" || rank == 0)
                    break;
                else if (c == ",")
                    rank++;
                else
                    break;
            }
            return rank;
        }
        /** Gets a pointer to the static fields of the current class. */
        get staticFieldsData() {
            return Il2Cpp.api.classGetStaticFieldData(this);
        }
        /** Gets the size of the instance - as a value type - of the current class. */
        get valueTypeSize() {
            return Il2Cpp.api.classGetValueTypeSize(this, NULL);
        }
        /** Gets the type of the current class. */
        get type() {
            return new Il2Cpp.Type(Il2Cpp.api.classGetType(this));
        }
        /** Allocates a new object of the current class. */
        alloc() {
            return new Il2Cpp.Object(Il2Cpp.api.objectNew(this));
        }
        /** Gets the field identified by the given name. */
        field(name) {
            return this.tryField(name) ?? raise(`couldn't find field ${name} in class ${this.type.name}`);
        }
        /** Builds a generic instance of the current generic class. */
        inflate(...classes) {
            if (!this.isGeneric) {
                raise(`cannot inflate class ${this.type.name} as it has no generic parameters`);
            }
            if (this.generics.length != classes.length) {
                raise(`cannot inflate class ${this.type.name} as it needs ${this.generics.length} generic parameter(s), not ${classes.length}`);
            }
            const types = classes.map(_ => _.type.object);
            const typeArray = Il2Cpp.array(Il2Cpp.corlib.class("System.Type"), types);
            const inflatedType = this.type.object.method("MakeGenericType", 1).invoke(typeArray);
            return new Il2Cpp.Class(Il2Cpp.api.classFromObject(inflatedType));
        }
        /** Calls the static constructor of the current class. */
        initialize() {
            Il2Cpp.api.classInitialize(this);
            return this;
        }
        /** Determines whether an instance of `other` class can be assigned to a variable of the current type. */
        isAssignableFrom(other) {
            return !!Il2Cpp.api.classIsAssignableFrom(this, other);
        }
        /** Determines whether the current class derives from `other` class. */
        isSubclassOf(other, checkInterfaces) {
            return !!Il2Cpp.api.classIsSubclassOf(this, other, +checkInterfaces);
        }
        /** Gets the method identified by the given name and parameter count. */
        method(name, parameterCount = -1) {
            return this.tryMethod(name, parameterCount) ?? raise(`couldn't find method ${name} in class ${this.type.name}`);
        }
        /** Gets the nested class with the given name. */
        nested(name) {
            return this.tryNested(name) ?? raise(`couldn't find nested class ${name} in class ${this.type.name}`);
        }
        /** Allocates a new object of the current class and calls its default constructor. */
        new() {
            const object = this.alloc();
            const exceptionArray = Memory.alloc(Process.pointerSize);
            Il2Cpp.api.objectInitialize(object, exceptionArray);
            const exception = exceptionArray.readPointer();
            if (!exception.isNull()) {
                raise(new Il2Cpp.Object(exception).toString());
            }
            return object;
        }
        /** Gets the field with the given name. */
        tryField(name) {
            return new Il2Cpp.Field(Il2Cpp.api.classGetFieldFromName(this, Memory.allocUtf8String(name))).asNullable();
        }
        /** Gets the method with the given name and parameter count. */
        tryMethod(name, parameterCount = -1) {
            return new Il2Cpp.Method(Il2Cpp.api.classGetMethodFromName(this, Memory.allocUtf8String(name), parameterCount)).asNullable();
        }
        /** Gets the nested class with the given name. */
        tryNested(name) {
            return this.nestedClasses.find(_ => _.name == name);
        }
        /** */
        toString() {
            const inherited = [this.parent].concat(this.interfaces);
            return `\
// ${this.assemblyName}
${this.isEnum ? `enum` : this.isStruct ? `struct` : this.isInterface ? `interface` : `class`} \
${this.type.name}\
${inherited ? ` : ${inherited.map(_ => _?.type.name).join(`, `)}` : ``}
{
    ${this.fields.join(`\n    `)}
    ${this.methods.join(`\n    `)}
}`;
        }
        /** Executes a callback for every defined class. */
        static enumerate(block) {
            const callback = new NativeCallback(_ => block(new Il2Cpp.Class(_)), "void", ["pointer", "pointer"]);
            return Il2Cpp.api.classForEach(callback, NULL);
        }
    };
    __decorate([
        lazy
    ], Class.prototype, "arrayClass", null);
    __decorate([
        lazy
    ], Class.prototype, "arrayElementSize", null);
    __decorate([
        lazy
    ], Class.prototype, "assemblyName", null);
    __decorate([
        lazy
    ], Class.prototype, "declaringClass", null);
    __decorate([
        lazy
    ], Class.prototype, "baseType", null);
    __decorate([
        lazy
    ], Class.prototype, "elementClass", null);
    __decorate([
        lazy
    ], Class.prototype, "fields", null);
    __decorate([
        lazy
    ], Class.prototype, "flags", null);
    __decorate([
        lazy
    ], Class.prototype, "fullName", null);
    __decorate([
        lazy
    ], Class.prototype, "generics", null);
    __decorate([
        lazy
    ], Class.prototype, "hasReferences", null);
    __decorate([
        lazy
    ], Class.prototype, "hasStaticConstructor", null);
    __decorate([
        lazy
    ], Class.prototype, "image", null);
    __decorate([
        lazy
    ], Class.prototype, "instanceSize", null);
    __decorate([
        lazy
    ], Class.prototype, "isAbstract", null);
    __decorate([
        lazy
    ], Class.prototype, "isBlittable", null);
    __decorate([
        lazy
    ], Class.prototype, "isEnum", null);
    __decorate([
        lazy
    ], Class.prototype, "isGeneric", null);
    __decorate([
        lazy
    ], Class.prototype, "isInflated", null);
    __decorate([
        lazy
    ], Class.prototype, "isInterface", null);
    __decorate([
        lazy
    ], Class.prototype, "isValueType", null);
    __decorate([
        lazy
    ], Class.prototype, "interfaces", null);
    __decorate([
        lazy
    ], Class.prototype, "methods", null);
    __decorate([
        lazy
    ], Class.prototype, "name", null);
    __decorate([
        lazy
    ], Class.prototype, "namespace", null);
    __decorate([
        lazy
    ], Class.prototype, "nestedClasses", null);
    __decorate([
        lazy
    ], Class.prototype, "parent", null);
    __decorate([
        lazy
    ], Class.prototype, "rank", null);
    __decorate([
        lazy
    ], Class.prototype, "staticFieldsData", null);
    __decorate([
        lazy
    ], Class.prototype, "valueTypeSize", null);
    __decorate([
        lazy
    ], Class.prototype, "type", null);
    Class = __decorate([
        recycle
    ], Class);
    Il2Cpp.Class = Class;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    /** Creates a delegate object of the given delegate class. */
    function delegate(klass, block) {
        const SystemDelegate = Il2Cpp.corlib.class("System.Delegate");
        const SystemMulticastDelegate = Il2Cpp.corlib.class("System.MulticastDelegate");
        if (!SystemDelegate.isAssignableFrom(klass)) {
            raise(`cannot create a delegate for ${klass.type.name} as it's a non-delegate class`);
        }
        if (klass.equals(SystemDelegate) || klass.equals(SystemMulticastDelegate)) {
            raise(`cannot create a delegate for neither ${SystemDelegate.type.name} nor ${SystemMulticastDelegate.type.name}, use a subclass instead`);
        }
        const delegate = klass.alloc();
        const key = delegate.handle.toString();
        const Invoke = delegate.tryMethod("Invoke") ?? raise(`cannot create a delegate for ${klass.type.name}, there is no Invoke method`);
        delegate.method(".ctor").invoke(delegate, Invoke.handle);
        const callback = Invoke.wrap(block);
        delegate.field("method_ptr").value = callback;
        delegate.field("invoke_impl").value = callback;
        Il2Cpp._callbacksToKeepAlive[key] = callback;
        return delegate;
    }
    Il2Cpp.delegate = delegate;
    /** @internal Used to prevent eager garbage collection against NativeCallbacks. */
    Il2Cpp._callbacksToKeepAlive = {};
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    let Domain = class Domain extends NativeStruct {
        /** Gets the assemblies that have been loaded into the execution context of the application domain. */
        get assemblies() {
            let handles = readNativeList(_ => Il2Cpp.api.domainGetAssemblies(this, _));
            if (handles.length == 0) {
                const assemblyObjects = this.object.method("GetAssemblies").overload().invoke();
                handles = globalThis.Array.from(assemblyObjects).map(_ => _.field("_mono_assembly").value);
            }
            return handles.map(_ => new Il2Cpp.Assembly(_));
        }
        /** Gets the encompassing object of the application domain. */
        get object() {
            return Il2Cpp.corlib.class("System.AppDomain").method("get_CurrentDomain").invoke();
        }
        /** Opens and loads the assembly with the given name. */
        assembly(name) {
            return this.tryAssembly(name) ?? raise(`couldn't find assembly ${name}`);
        }
        /** Attached a new thread to the application domain. */
        attach() {
            return new Il2Cpp.Thread(Il2Cpp.api.threadAttach(this));
        }
        /** Opens and loads the assembly with the given name. */
        tryAssembly(name) {
            return new Il2Cpp.Assembly(Il2Cpp.api.domainGetAssemblyFromName(this, Memory.allocUtf8String(name))).asNullable();
        }
    };
    __decorate([
        lazy
    ], Domain.prototype, "assemblies", null);
    __decorate([
        lazy
    ], Domain.prototype, "object", null);
    Domain = __decorate([
        recycle
    ], Domain);
    Il2Cpp.Domain = Domain;
    // prettier-ignore
    getter(Il2Cpp, "domain", () => {
        return new Il2Cpp.Domain(Il2Cpp.api.domainGet());
    }, lazy);
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Field extends NativeStruct {
        /** Gets the class in which this field is defined. */
        get class() {
            return new Il2Cpp.Class(Il2Cpp.api.fieldGetClass(this));
        }
        /** Gets the flags of the current field. */
        get flags() {
            return Il2Cpp.api.fieldGetFlags(this);
        }
        /** Determines whether this field value is known at compile time. */
        get isLiteral() {
            return (this.flags & 64 /* Il2Cpp.Field.Attributes.Literal */) != 0;
        }
        /** Determines whether this field is static. */
        get isStatic() {
            return (this.flags & 16 /* Il2Cpp.Field.Attributes.Static */) != 0;
        }
        /** Determines whether this field is thread static. */
        get isThreadStatic() {
            const offset = Il2Cpp.corlib.class("System.AppDomain").field("type_resolve_in_progress").offset;
            // prettier-ignore
            getter(Il2Cpp.Field.prototype, "isThreadStatic", function () {
                return this.offset == offset;
            }, lazy);
            return this.isThreadStatic;
        }
        /** Gets the access modifier of this field. */
        get modifier() {
            switch (this.flags & 7 /* Il2Cpp.Field.Attributes.FieldAccessMask */) {
                case 1 /* Il2Cpp.Field.Attributes.Private */:
                    return "private";
                case 2 /* Il2Cpp.Field.Attributes.FamilyAndAssembly */:
                    return "private protected";
                case 3 /* Il2Cpp.Field.Attributes.Assembly */:
                    return "internal";
                case 4 /* Il2Cpp.Field.Attributes.Family */:
                    return "protected";
                case 5 /* Il2Cpp.Field.Attributes.FamilyOrAssembly */:
                    return "protected internal";
                case 6 /* Il2Cpp.Field.Attributes.Public */:
                    return "public";
            }
        }
        /** Gets the name of this field. */
        get name() {
            return Il2Cpp.api.fieldGetName(this).readUtf8String();
        }
        /** Gets the offset of this field, calculated as the difference with its owner virtual address. */
        get offset() {
            return Il2Cpp.api.fieldGetOffset(this);
        }
        /** Gets the type of this field. */
        get type() {
            return new Il2Cpp.Type(Il2Cpp.api.fieldGetType(this));
        }
        /** Gets the value of this field. */
        get value() {
            if (!this.isStatic) {
                raise(`cannot access instance field ${this.class.type.name}::${this.name} from a class, use an object instead`);
            }
            const handle = Memory.alloc(Process.pointerSize);
            Il2Cpp.api.fieldGetStaticValue(this.handle, handle);
            return Il2Cpp.read(handle, this.type);
        }
        /** Sets the value of this field. Thread static or literal values cannot be altered yet. */
        set value(value) {
            if (!this.isStatic) {
                raise(`cannot access instance field ${this.class.type.name}::${this.name} from a class, use an object instead`);
            }
            if (this.isThreadStatic || this.isLiteral) {
                raise(`cannot write the value of field ${this.name} as it's thread static or literal`);
            }
            const handle = 
            // pointer-like values should be passed as-is, but boxed
            // value types (primitives included) must be unboxed first
            value instanceof Il2Cpp.Object && this.type.class.isValueType
                ? value.unbox()
                : value instanceof NativeStruct
                    ? value.handle
                    : value instanceof NativePointer
                        ? value
                        : Il2Cpp.write(Memory.alloc(this.type.class.valueTypeSize), value, this.type);
            Il2Cpp.api.fieldSetStaticValue(this.handle, handle);
        }
        /** */
        toString() {
            return `\
${this.isThreadStatic ? `[ThreadStatic] ` : ``}\
${this.isStatic ? `static ` : ``}\
${this.type.name} \
${this.name}\
${this.isLiteral ? ` = ${this.type.class.isEnum ? Il2Cpp.read(this.value.handle, this.type.class.baseType) : this.value}` : ``};\
${this.isThreadStatic || this.isLiteral ? `` : ` // 0x${this.offset.toString(16)}`}`;
        }
        /** @internal */
        withHolder(instance) {
            if (this.isStatic) {
                raise(`cannot access static field ${this.class.type.name}::${this.name} from an object, use a class instead`);
            }
            const valueHandle = instance.handle.add(this.offset - (instance instanceof Il2Cpp.ValueType ? Il2Cpp.Object.headerSize : 0));
            return new Proxy(this, {
                get(target, property) {
                    if (property == "value") {
                        return Il2Cpp.read(valueHandle, target.type);
                    }
                    return Reflect.get(target, property);
                },
                set(target, property, value) {
                    if (property == "value") {
                        Il2Cpp.write(valueHandle, value, target.type);
                        return true;
                    }
                    return Reflect.set(target, property, value);
                }
            });
        }
    }
    __decorate([
        lazy
    ], Field.prototype, "class", null);
    __decorate([
        lazy
    ], Field.prototype, "flags", null);
    __decorate([
        lazy
    ], Field.prototype, "isLiteral", null);
    __decorate([
        lazy
    ], Field.prototype, "isStatic", null);
    __decorate([
        lazy
    ], Field.prototype, "isThreadStatic", null);
    __decorate([
        lazy
    ], Field.prototype, "modifier", null);
    __decorate([
        lazy
    ], Field.prototype, "name", null);
    __decorate([
        lazy
    ], Field.prototype, "offset", null);
    __decorate([
        lazy
    ], Field.prototype, "type", null);
    Il2Cpp.Field = Field;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class GCHandle {
        handle;
        /** @internal */
        constructor(handle) {
            this.handle = handle;
        }
        /** Gets the object associated to this handle. */
        get target() {
            return new Il2Cpp.Object(Il2Cpp.api.gcHandleGetTarget(this.handle)).asNullable();
        }
        /** Frees this handle. */
        free() {
            return Il2Cpp.api.gcHandleFree(this.handle);
        }
    }
    Il2Cpp.GCHandle = GCHandle;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    let Image = class Image extends NativeStruct {
        /** Gets the assembly in which the current image is defined. */
        get assembly() {
            return new Il2Cpp.Assembly(Il2Cpp.api.imageGetAssembly(this));
        }
        /** Gets the amount of classes defined in this image. */
        get classCount() {
            if (Il2Cpp.unityVersionIsBelow201830) {
                return this.classes.length;
            }
            else {
                return Il2Cpp.api.imageGetClassCount(this);
            }
        }
        /** Gets the classes defined in this image. */
        get classes() {
            if (Il2Cpp.unityVersionIsBelow201830) {
                const types = this.assembly.object.method("GetTypes").invoke(false);
                // In Unity 5.3.8f1, getting System.Reflection.Emit.OpCodes type name
                // without iterating all the classes first somehow blows things up at
                // app startup, hence the `Array.from`.
                const classes = globalThis.Array.from(types, _ => new Il2Cpp.Class(Il2Cpp.api.classFromObject(_)));
                classes.unshift(this.class("<Module>"));
                return classes;
            }
            else {
                return globalThis.Array.from(globalThis.Array(this.classCount), (_, i) => new Il2Cpp.Class(Il2Cpp.api.imageGetClass(this, i)));
            }
        }
        /** Gets the name of this image. */
        get name() {
            return Il2Cpp.api.imageGetName(this).readUtf8String();
        }
        /** Gets the class with the specified name defined in this image. */
        class(name) {
            return this.tryClass(name) ?? raise(`couldn't find class ${name} in assembly ${this.name}`);
        }
        /** Gets the class with the specified name defined in this image. */
        tryClass(name) {
            const dotIndex = name.lastIndexOf(".");
            const classNamespace = Memory.allocUtf8String(dotIndex == -1 ? "" : name.slice(0, dotIndex));
            const className = Memory.allocUtf8String(name.slice(dotIndex + 1));
            return new Il2Cpp.Class(Il2Cpp.api.classFromName(this, classNamespace, className)).asNullable();
        }
    };
    __decorate([
        lazy
    ], Image.prototype, "assembly", null);
    __decorate([
        lazy
    ], Image.prototype, "classCount", null);
    __decorate([
        lazy
    ], Image.prototype, "classes", null);
    __decorate([
        lazy
    ], Image.prototype, "name", null);
    Image = __decorate([
        recycle
    ], Image);
    Il2Cpp.Image = Image;
    // prettier-ignore
    getter(Il2Cpp, "corlib", () => {
        return new Il2Cpp.Image(Il2Cpp.api.getCorlib());
    }, lazy);
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class MemorySnapshot extends NativeStruct {
        /** Captures a memory snapshot. */
        static capture() {
            return new Il2Cpp.MemorySnapshot();
        }
        /** Creates a memory snapshot with the given handle. */
        constructor(handle = Il2Cpp.api.memorySnapshotCapture()) {
            super(handle);
        }
        /** Gets any initialized class. */
        get classes() {
            return readNativeIterator(_ => Il2Cpp.api.memorySnapshotGetClasses(this, _)).map(_ => new Il2Cpp.Class(_));
        }
        /** Gets the objects tracked by this memory snapshot. */
        get objects() {
            // prettier-ignore
            return readNativeList(_ => Il2Cpp.api.memorySnapshotGetObjects(this, _)).filter(_ => !_.isNull()).map(_ => new Il2Cpp.Object(_));
        }
        /** Frees this memory snapshot. */
        free() {
            Il2Cpp.api.memorySnapshotFree(this);
        }
    }
    __decorate([
        lazy
    ], MemorySnapshot.prototype, "classes", null);
    __decorate([
        lazy
    ], MemorySnapshot.prototype, "objects", null);
    Il2Cpp.MemorySnapshot = MemorySnapshot;
    /** */
    function memorySnapshot(block) {
        const memorySnapshot = Il2Cpp.MemorySnapshot.capture();
        const result = block(memorySnapshot);
        memorySnapshot.free();
        return result;
    }
    Il2Cpp.memorySnapshot = memorySnapshot;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Method extends NativeStruct {
        /** Gets the class in which this method is defined. */
        get class() {
            return new Il2Cpp.Class(Il2Cpp.api.methodGetClass(this));
        }
        /** Gets the flags of the current method. */
        get flags() {
            return Il2Cpp.api.methodGetFlags(this, NULL);
        }
        /** Gets the implementation flags of the current method. */
        get implementationFlags() {
            const implementationFlagsPointer = Memory.alloc(Process.pointerSize);
            Il2Cpp.api.methodGetFlags(this, implementationFlagsPointer);
            return implementationFlagsPointer.readU32();
        }
        /** */
        get fridaSignature() {
            const types = [];
            for (const parameter of this.parameters) {
                types.push(parameter.type.fridaAlias);
            }
            if (!this.isStatic || Il2Cpp.unityVersionIsBelow201830) {
                types.unshift("pointer");
            }
            if (this.isInflated) {
                types.push("pointer");
            }
            return types;
        }
        /** Gets the generic parameters of this generic method. */
        get generics() {
            if (!this.isGeneric && !this.isInflated) {
                return [];
            }
            const types = this.object.method("GetGenericArguments").invoke();
            return globalThis.Array.from(types).map(_ => new Il2Cpp.Class(Il2Cpp.api.classFromObject(_)));
        }
        /** Determines whether this method is external. */
        get isExternal() {
            return (this.implementationFlags & 4096 /* Il2Cpp.Method.ImplementationAttribute.InternalCall */) != 0;
        }
        /** Determines whether this method is generic. */
        get isGeneric() {
            return !!Il2Cpp.api.methodIsGeneric(this);
        }
        /** Determines whether this method is inflated (generic with a concrete type parameter). */
        get isInflated() {
            return !!Il2Cpp.api.methodIsInflated(this);
        }
        /** Determines whether this method is static. */
        get isStatic() {
            return !Il2Cpp.api.methodIsInstance(this);
        }
        /** Determines whether this method is synchronized. */
        get isSynchronized() {
            return (this.implementationFlags & 32 /* Il2Cpp.Method.ImplementationAttribute.Synchronized */) != 0;
        }
        /** Gets the access modifier of this method. */
        get modifier() {
            switch (this.flags & 7 /* Il2Cpp.Method.Attributes.MemberAccessMask */) {
                case 1 /* Il2Cpp.Method.Attributes.Private */:
                    return "private";
                case 2 /* Il2Cpp.Method.Attributes.FamilyAndAssembly */:
                    return "private protected";
                case 3 /* Il2Cpp.Method.Attributes.Assembly */:
                    return "internal";
                case 4 /* Il2Cpp.Method.Attributes.Family */:
                    return "protected";
                case 5 /* Il2Cpp.Method.Attributes.FamilyOrAssembly */:
                    return "protected internal";
                case 6 /* Il2Cpp.Method.Attributes.Public */:
                    return "public";
            }
        }
        /** Gets the name of this method. */
        get name() {
            return Il2Cpp.api.methodGetName(this).readUtf8String();
        }
        /** @internal */
        get nativeFunction() {
            return new NativeFunction(this.virtualAddress, this.returnType.fridaAlias, this.fridaSignature);
        }
        /** Gets the encompassing object of the current method. */
        get object() {
            return new Il2Cpp.Object(Il2Cpp.api.methodGetObject(this, NULL));
        }
        /** Gets the amount of parameters of this method. */
        get parameterCount() {
            return Il2Cpp.api.methodGetParameterCount(this);
        }
        /** Gets the parameters of this method. */
        get parameters() {
            return globalThis.Array.from(globalThis.Array(this.parameterCount), (_, i) => {
                const parameterName = Il2Cpp.api.methodGetParameterName(this, i).readUtf8String();
                const parameterType = Il2Cpp.api.methodGetParameterType(this, i);
                return new Il2Cpp.Parameter(parameterName, i, new Il2Cpp.Type(parameterType));
            });
        }
        /** Gets the relative virtual address (RVA) of this method. */
        get relativeVirtualAddress() {
            return this.virtualAddress.sub(Il2Cpp.module.base);
        }
        /** Gets the return type of this method. */
        get returnType() {
            return new Il2Cpp.Type(Il2Cpp.api.methodGetReturnType(this));
        }
        /** Gets the virtual address (VA) of this method. */
        get virtualAddress() {
            const FilterTypeName = Il2Cpp.corlib.class("System.Reflection.Module").initialize().field("FilterTypeName").value;
            const FilterTypeNameMethodPointer = FilterTypeName.field("method_ptr").value;
            const FilterTypeNameMethod = FilterTypeName.field("method").value;
            // prettier-ignore
            const offset = FilterTypeNameMethod.offsetOf(_ => _.readPointer().equals(FilterTypeNameMethodPointer))
                ?? raise("couldn't find the virtual address offset in the native method struct");
            // prettier-ignore
            getter(Il2Cpp.Method.prototype, "virtualAddress", function () {
                return this.handle.add(offset).readPointer();
            }, lazy);
            // In Unity 2017.4.40f1 (don't know about others),
            // `Il2Cpp.Class::initialize` somehow triggers a nasty bug during
            // early instrumentation, so that we aren't able to obtain the
            // offset to get the virtual address of a method when the script
            // is reloaded. A workaround consists in manually re-invoking the
            // static constructor.
            Il2Cpp.corlib.class("System.Reflection.Module").method(".cctor").invoke();
            return this.virtualAddress;
        }
        /** Replaces the body of this method. */
        set implementation(block) {
            try {
                Interceptor.replace(this.virtualAddress, this.wrap(block));
            }
            catch (e) {
                switch (e.message) {
                    case "access violation accessing 0x0":
                        raise(`couldn't set implementation for method ${this.name} as it has a NULL virtual address`);
                    case /unable to intercept function at \w+; please file a bug/.exec(e.message)?.input:
                        warn(`couldn't set implementation for method ${this.name} as it may be a thunk`);
                        break;
                    case "already replaced this function":
                        warn(`couldn't set implementation for method ${this.name} as it has already been replaced by a thunk`);
                        break;
                    default:
                        throw e;
                }
            }
        }
        /** Creates a generic instance of the current generic method. */
        inflate(...classes) {
            if (!this.isGeneric) {
                raise(`cannot inflate method ${this.name} as it has no generic parameters`);
            }
            if (this.generics.length != classes.length) {
                raise(`cannot inflate method ${this.name} as it needs ${this.generics.length} generic parameter(s), not ${classes.length}`);
            }
            const types = classes.map(_ => _.type.object);
            const typeArray = Il2Cpp.array(Il2Cpp.corlib.class("System.Type"), types);
            const inflatedMethodObject = this.object.method("MakeGenericMethod", 1).invoke(typeArray);
            return new Il2Cpp.Method(inflatedMethodObject.field("mhandle").value);
        }
        /** Invokes this method. */
        invoke(...parameters) {
            if (!this.isStatic) {
                raise(`cannot invoke non-static method ${this.name} as it must be invoked throught a Il2Cpp.Object, not a Il2Cpp.Class`);
            }
            return this.invokeRaw(NULL, ...parameters);
        }
        /** @internal */
        invokeRaw(instance, ...parameters) {
            const allocatedParameters = parameters.map(Il2Cpp.toFridaValue);
            if (!this.isStatic || Il2Cpp.unityVersionIsBelow201830) {
                allocatedParameters.unshift(instance);
            }
            if (this.isInflated) {
                allocatedParameters.push(this.handle);
            }
            try {
                const returnValue = this.nativeFunction(...allocatedParameters);
                return Il2Cpp.fromFridaValue(returnValue, this.returnType);
            }
            catch (e) {
                if (e == null) {
                    raise("an unexpected native invocation exception occurred, this is due to parameter types mismatch");
                }
                switch (e.message) {
                    case "bad argument count":
                        raise(`couldn't invoke method ${this.name} as it needs ${this.parameterCount} parameter(s), not ${parameters.length}`);
                    case "expected a pointer":
                    case "expected number":
                    case "expected array with fields":
                        raise(`couldn't invoke method ${this.name} using incorrect parameter types`);
                }
                throw e;
            }
        }
        /** Gets the overloaded method with the given parameter types. */
        overload(...parameterTypes) {
            const result = this.tryOverload(...parameterTypes);
            if (result != undefined)
                return result;
            raise(`couldn't find overloaded method ${this.name}(${parameterTypes})`);
        }
        /** Gets the parameter with the given name. */
        parameter(name) {
            return this.tryParameter(name) ?? raise(`couldn't find parameter ${name} in method ${this.name}`);
        }
        /** Restore the original method implementation. */
        revert() {
            Interceptor.revert(this.virtualAddress);
            Interceptor.flush();
        }
        /** Gets the overloaded method with the given parameter types. */
        tryOverload(...parameterTypes) {
            let klass = this.class;
            while (klass) {
                const method = klass.methods.find(method => {
                    return (method.name == this.name &&
                        method.parameterCount == parameterTypes.length &&
                        method.parameters.every((e, i) => e.type.name == parameterTypes[i]));
                });
                if (method) {
                    return method;
                }
                klass = klass.parent;
            }
            return undefined;
        }
        /** Gets the parameter with the given name. */
        tryParameter(name) {
            return this.parameters.find(_ => _.name == name);
        }
        /** */
        toString() {
            return `\
${this.isStatic ? `static ` : ``}\
${this.returnType.name} \
${this.name}\
(${this.parameters.join(`, `)});\
${this.virtualAddress.isNull() ? `` : ` // 0x${this.relativeVirtualAddress.toString(16).padStart(8, `0`)}`}`;
        }
        /** @internal */
        withHolder(instance) {
            if (this.isStatic) {
                raise(`cannot access static method ${this.class.type.name}::${this.name} from an object, use a class instead`);
            }
            return new Proxy(this, {
                get(target, property) {
                    switch (property) {
                        case "invoke":
                            // In Unity 5.3.5f1 and >= 2021.2.0f1, value types
                            // methods may assume their `this` parameter is a
                            // pointer to raw data (that is how value types are
                            // layed out in memory) instead of a pointer to an
                            // object (that is object header + raw data).
                            // In any case, they also don't use whatever there
                            // is in the object header, so we can safely "skip"
                            // the object header by adding the object header
                            // size to the object (a boxed value type) handle.
                            const handle = instance instanceof Il2Cpp.ValueType
                                ? target.class.isValueType
                                    ? instance.handle.add(maybeObjectHeaderSize() - Il2Cpp.Object.headerSize)
                                    : raise(`cannot invoke method ${target.class.type.name}::${target.name} against a value type, you must box it first`)
                                : target.class.isValueType
                                    ? instance.handle.add(maybeObjectHeaderSize())
                                    : instance.handle;
                            return target.invokeRaw.bind(target, handle);
                        case "inflate":
                        case "overload":
                        case "tryOverload":
                            return function (...args) {
                                return target[property](...args)?.withHolder(instance);
                            };
                    }
                    return Reflect.get(target, property);
                }
            });
        }
        /** @internal */
        wrap(block) {
            const startIndex = +!this.isStatic | +Il2Cpp.unityVersionIsBelow201830;
            return new NativeCallback((...args) => {
                const thisObject = this.isStatic
                    ? this.class
                    : this.class.isValueType
                        ? new Il2Cpp.ValueType(args[0].add(Il2Cpp.Object.headerSize - maybeObjectHeaderSize()), this.class.type)
                        : new Il2Cpp.Object(args[0]);
                const parameters = this.parameters.map((_, i) => Il2Cpp.fromFridaValue(args[i + startIndex], _.type));
                const result = block.call(thisObject, ...parameters);
                return Il2Cpp.toFridaValue(result);
            }, this.returnType.fridaAlias, this.fridaSignature);
        }
    }
    __decorate([
        lazy
    ], Method.prototype, "class", null);
    __decorate([
        lazy
    ], Method.prototype, "flags", null);
    __decorate([
        lazy
    ], Method.prototype, "implementationFlags", null);
    __decorate([
        lazy
    ], Method.prototype, "fridaSignature", null);
    __decorate([
        lazy
    ], Method.prototype, "generics", null);
    __decorate([
        lazy
    ], Method.prototype, "isExternal", null);
    __decorate([
        lazy
    ], Method.prototype, "isGeneric", null);
    __decorate([
        lazy
    ], Method.prototype, "isInflated", null);
    __decorate([
        lazy
    ], Method.prototype, "isStatic", null);
    __decorate([
        lazy
    ], Method.prototype, "isSynchronized", null);
    __decorate([
        lazy
    ], Method.prototype, "modifier", null);
    __decorate([
        lazy
    ], Method.prototype, "name", null);
    __decorate([
        lazy
    ], Method.prototype, "nativeFunction", null);
    __decorate([
        lazy
    ], Method.prototype, "object", null);
    __decorate([
        lazy
    ], Method.prototype, "parameterCount", null);
    __decorate([
        lazy
    ], Method.prototype, "parameters", null);
    __decorate([
        lazy
    ], Method.prototype, "relativeVirtualAddress", null);
    __decorate([
        lazy
    ], Method.prototype, "returnType", null);
    Il2Cpp.Method = Method;
    let maybeObjectHeaderSize = () => {
        const struct = Il2Cpp.corlib.class("System.RuntimeTypeHandle").initialize().alloc();
        struct.method(".ctor").invokeRaw(struct, ptr(0xdeadbeef));
        // Here we check where the sentinel value is
        // if it's not where it is supposed to be, it means struct methods
        // assume they are receiving value types (that is a pointer to raw data)
        // hence, we must "skip" the object header when invoking such methods.
        const offset = struct.field("value").value.equals(ptr(0xdeadbeef)) ? 0 : Il2Cpp.Object.headerSize;
        return (maybeObjectHeaderSize = () => offset)();
    };
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Object extends NativeStruct {
        /** Gets the Il2CppObject struct size, possibly equal to `Process.pointerSize * 2`. */
        static get headerSize() {
            return Il2Cpp.corlib.class("System.Object").instanceSize;
        }
        /** Gets the class of this object. */
        get class() {
            return new Il2Cpp.Class(Il2Cpp.api.objectGetClass(this));
        }
        /** Returns a monitor for this object. */
        get monitor() {
            return new Il2Cpp.Object.Monitor(this);
        }
        /** Gets the size of the current object. */
        get size() {
            return Il2Cpp.api.objectGetSize(this);
        }
        /** Gets the field with the given name. */
        field(name) {
            return this.class.field(name).withHolder(this);
        }
        /** Gets the method with the given name. */
        method(name, parameterCount = -1) {
            return this.class.method(name, parameterCount).withHolder(this);
        }
        /** Creates a reference to this object. */
        ref(pin) {
            return new Il2Cpp.GCHandle(Il2Cpp.api.gcHandleNew(this, +pin));
        }
        /** Gets the correct virtual method from the given virtual method. */
        virtualMethod(method) {
            return new Il2Cpp.Method(Il2Cpp.api.objectGetVirtualMethod(this, method)).withHolder(this);
        }
        /** Gets the field with the given name. */
        tryField(name) {
            return this.class.tryField(name)?.withHolder(this);
        }
        /** Gets the field with the given name. */
        tryMethod(name, parameterCount = -1) {
            return this.class.tryMethod(name, parameterCount)?.withHolder(this);
        }
        /** */
        toString() {
            return this.isNull() ? "null" : this.method("ToString", 0).invoke().content ?? "null";
        }
        /** Unboxes the value type (either a primitive, a struct or an enum) out of this object. */
        unbox() {
            return this.class.isValueType
                ? new Il2Cpp.ValueType(Il2Cpp.api.objectUnbox(this), this.class.type)
                : raise(`couldn't unbox instances of ${this.class.type.name} as they are not value types`);
        }
        /** Creates a weak reference to this object. */
        weakRef(trackResurrection) {
            return new Il2Cpp.GCHandle(Il2Cpp.api.gcHandleNewWeakRef(this, +trackResurrection));
        }
    }
    __decorate([
        lazy
    ], Object.prototype, "class", null);
    __decorate([
        lazy
    ], Object.prototype, "size", null);
    __decorate([
        lazy
    ], Object, "headerSize", null);
    Il2Cpp.Object = Object;
    (function (Object) {
        class Monitor {
            handle;
            /** @internal */
            constructor(/** @internal */ handle) {
                this.handle = handle;
            }
            /** Acquires an exclusive lock on the current object. */
            enter() {
                return Il2Cpp.api.monitorEnter(this.handle);
            }
            /** Release an exclusive lock on the current object. */
            exit() {
                return Il2Cpp.api.monitorExit(this.handle);
            }
            /** Notifies a thread in the waiting queue of a change in the locked object's state. */
            pulse() {
                return Il2Cpp.api.monitorPulse(this.handle);
            }
            /** Notifies all waiting threads of a change in the object's state. */
            pulseAll() {
                return Il2Cpp.api.monitorPulseAll(this.handle);
            }
            /** Attempts to acquire an exclusive lock on the current object. */
            tryEnter(timeout) {
                return !!Il2Cpp.api.monitorTryEnter(this.handle, timeout);
            }
            /** Releases the lock on an object and attempts to block the current thread until it reacquires the lock. */
            tryWait(timeout) {
                return !!Il2Cpp.api.monitorTryWait(this.handle, timeout);
            }
            /** Releases the lock on an object and blocks the current thread until it reacquires the lock. */
            wait() {
                return Il2Cpp.api.monitorWait(this.handle);
            }
        }
        Object.Monitor = Monitor;
    })(Object = Il2Cpp.Object || (Il2Cpp.Object = {}));
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Parameter {
        /** Name of this parameter. */
        name;
        /** Position of this parameter. */
        position;
        /** Type of this parameter. */
        type;
        constructor(name, position, type) {
            this.name = name;
            this.position = position;
            this.type = type;
        }
        /** */
        toString() {
            return `${this.type.name} ${this.name}`;
        }
    }
    Il2Cpp.Parameter = Parameter;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Pointer extends NativeStruct {
        type;
        constructor(handle, type) {
            super(handle);
            this.type = type;
        }
        /** Gets the element at the given index. */
        get(index) {
            return Il2Cpp.read(this.handle.add(index * this.type.class.arrayElementSize), this.type);
        }
        /** Reads the given amount of elements starting at the given offset. */
        read(length, offset = 0) {
            const values = new globalThis.Array(length);
            for (let i = 0; i < length; i++) {
                values[i] = this.get(i + offset);
            }
            return values;
        }
        /** Sets the given element at the given index */
        set(index, value) {
            Il2Cpp.write(this.handle.add(index * this.type.class.arrayElementSize), value, this.type);
        }
        /** */
        toString() {
            return this.handle.toString();
        }
        /** Writes the given elements starting at the given index. */
        write(values, offset = 0) {
            for (let i = 0; i < values.length; i++) {
                this.set(i + offset, values[i]);
            }
        }
    }
    Il2Cpp.Pointer = Pointer;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Reference extends NativeStruct {
        type;
        constructor(handle, type) {
            super(handle);
            this.type = type;
        }
        /** Gets the element referenced by the current reference. */
        get value() {
            return Il2Cpp.read(this.handle, this.type);
        }
        /** Sets the element referenced by the current reference. */
        set value(value) {
            Il2Cpp.write(this.handle, value, this.type);
        }
        /** */
        toString() {
            return this.isNull() ? "null" : `->${this.value}`;
        }
    }
    Il2Cpp.Reference = Reference;
    /** Creates a reference to the specified value. */
    function reference(value, type) {
        const handle = Memory.alloc(Process.pointerSize);
        switch (typeof value) {
            case "boolean":
                return new Il2Cpp.Reference(handle.writeS8(+value), Il2Cpp.corlib.class("System.Boolean").type);
            case "number":
                switch (type?.typeEnum) {
                    case Il2Cpp.Type.enum.unsignedByte:
                        return new Il2Cpp.Reference(handle.writeU8(value), type);
                    case Il2Cpp.Type.enum.byte:
                        return new Il2Cpp.Reference(handle.writeS8(value), type);
                    case Il2Cpp.Type.enum.char:
                    case Il2Cpp.Type.enum.unsignedShort:
                        return new Il2Cpp.Reference(handle.writeU16(value), type);
                    case Il2Cpp.Type.enum.short:
                        return new Il2Cpp.Reference(handle.writeS16(value), type);
                    case Il2Cpp.Type.enum.unsignedInt:
                        return new Il2Cpp.Reference(handle.writeU32(value), type);
                    case Il2Cpp.Type.enum.int:
                        return new Il2Cpp.Reference(handle.writeS32(value), type);
                    case Il2Cpp.Type.enum.unsignedLong:
                        return new Il2Cpp.Reference(handle.writeU64(value), type);
                    case Il2Cpp.Type.enum.long:
                        return new Il2Cpp.Reference(handle.writeS64(value), type);
                    case Il2Cpp.Type.enum.float:
                        return new Il2Cpp.Reference(handle.writeFloat(value), type);
                    case Il2Cpp.Type.enum.double:
                        return new Il2Cpp.Reference(handle.writeDouble(value), type);
                }
            case "object":
                if (value instanceof Il2Cpp.ValueType || value instanceof Il2Cpp.Pointer) {
                    return new Il2Cpp.Reference(value.handle, value.type);
                }
                else if (value instanceof Il2Cpp.Object) {
                    return new Il2Cpp.Reference(handle.writePointer(value), value.class.type);
                }
                else if (value instanceof Il2Cpp.String || value instanceof Il2Cpp.Array) {
                    return new Il2Cpp.Reference(handle.writePointer(value), value.object.class.type);
                }
                else if (value instanceof NativePointer) {
                    switch (type?.typeEnum) {
                        case Il2Cpp.Type.enum.unsignedNativePointer:
                        case Il2Cpp.Type.enum.nativePointer:
                            return new Il2Cpp.Reference(handle.writePointer(value), type);
                    }
                }
                else if (value instanceof Int64) {
                    return new Il2Cpp.Reference(handle.writeS64(value), Il2Cpp.corlib.class("System.Int64").type);
                }
                else if (value instanceof UInt64) {
                    return new Il2Cpp.Reference(handle.writeU64(value), Il2Cpp.corlib.class("System.UInt64").type);
                }
            default:
                raise(`couldn't create a reference to ${value} using an unhandled type ${type?.name}`);
        }
    }
    Il2Cpp.reference = reference;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class String extends NativeStruct {
        /** Gets the content of this string. */
        get content() {
            return Il2Cpp.api.stringGetChars(this).readUtf16String(this.length);
        }
        /** @unsafe Sets the content of this string - it may write out of bounds! */
        set content(value) {
            // prettier-ignore
            const offset = Il2Cpp.string("vfsfitvnm").handle.offsetOf(_ => _.readInt() == 9)
                ?? raise("couldn't find the length offset in the native string struct");
            globalThis.Object.defineProperty(Il2Cpp.String.prototype, "content", {
                set(value) {
                    Il2Cpp.api.stringGetChars(this).writeUtf16String(value ?? "");
                    this.handle.add(offset).writeS32(value?.length ?? 0);
                }
            });
            this.content = value;
        }
        /** Gets the length of this string. */
        get length() {
            return Il2Cpp.api.stringGetLength(this);
        }
        /** Gets the encompassing object of the current string. */
        get object() {
            return new Il2Cpp.Object(this);
        }
        /** */
        toString() {
            return this.isNull() ? "null" : `"${this.content}"`;
        }
    }
    Il2Cpp.String = String;
    /** Creates a new string with the specified content. */
    function string(content) {
        return new Il2Cpp.String(Il2Cpp.api.stringNew(Memory.allocUtf8String(content ?? "")));
    }
    Il2Cpp.string = string;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class Thread extends NativeStruct {
        /** Gets the native id of the current thread. */
        get id() {
            let get = function () {
                return this.internal.field("thread_id").value.toNumber();
            };
            // https://github.com/mono/linux-packaging-mono/blob/d586f84dfea30217f34b076a616a098518aa72cd/mono/utils/mono-threads.h#L642
            if (Process.platform != "windows") {
                const currentThreadId = Process.getCurrentThreadId();
                const currentPosixThread = ptr(get.apply(Il2Cpp.currentThread));
                // prettier-ignore
                const offset = currentPosixThread.offsetOf(_ => _.readS32() == currentThreadId, 1024) ??
                    raise(`couldn't find the offset for determining the kernel id of a posix thread`);
                const _get = get;
                get = function () {
                    return ptr(_get.apply(this)).add(offset).readS32();
                };
            }
            getter(Il2Cpp.Thread.prototype, "id", get, lazy);
            return this.id;
        }
        /** Gets the encompassing internal object (System.Threding.InternalThreead) of the current thread. */
        get internal() {
            return this.object.tryField("internal_thread")?.value ?? this.object;
        }
        /** Determines whether the current thread is the garbage collector finalizer one. */
        get isFinalizer() {
            return !Il2Cpp.api.threadIsVm(this);
        }
        /** Gets the managed id of the current thread. */
        get managedId() {
            return this.object.method("get_ManagedThreadId").invoke();
        }
        /** Gets the encompassing object of the current thread. */
        get object() {
            return new Il2Cpp.Object(this);
        }
        /** @internal */
        get staticData() {
            return this.internal.field("static_data").value;
        }
        /** @internal */
        get synchronizationContext() {
            const get_ExecutionContext = this.object.tryMethod("GetMutableExecutionContext") ?? this.object.method("get_ExecutionContext");
            const executionContext = get_ExecutionContext.invoke();
            let synchronizationContext = executionContext.tryField("_syncContext")?.value ??
                executionContext.tryMethod("get_SynchronizationContext")?.invoke() ??
                this.tryLocalValue(Il2Cpp.corlib.class("System.Threading.SynchronizationContext"));
            if (synchronizationContext == null || synchronizationContext.isNull()) {
                if (this.handle.equals(Il2Cpp.mainThread.handle)) {
                    raise(`couldn't find the synchronization context of the main thread, perhaps this is early instrumentation?`);
                }
                else {
                    raise(`couldn't find the synchronization context of thread #${this.managedId}, only the main thread is expected to have one`);
                }
            }
            return synchronizationContext;
        }
        /** Detaches the thread from the application domain. */
        detach() {
            return Il2Cpp.api.threadDetach(this);
        }
        /** Schedules a callback on the current thread. */
        schedule(block) {
            const Post = this.synchronizationContext.method("Post");
            return new Promise(resolve => {
                const delegate = Il2Cpp.delegate(Il2Cpp.corlib.class("System.Threading.SendOrPostCallback"), () => {
                    const result = block();
                    setImmediate(() => resolve(result));
                });
                // This is to replace pending scheduled callbacks when the script is about to get unlaoded.
                // If we skip this cleanup, Frida's native callbacks will point to invalid memory, making
                // the application crash as soon as the IL2CPP runtime tries to execute such callbacks.
                // For instance, without the following code, this is how you can trigger a crash:
                // 1) unfocus the application;
                // 2) schedule a callback;
                // 3) reload the script;
                // 4) focus application.
                //
                // The "proper" solution consists in removing our delegates from the Unity synchroniztion
                // context, but the interface is not consisent across Unity versions - e.g. 2017.4.40f1 uses
                // a queue instead of a list, whereas newer versions do not allow null work requests.
                // The following solution, which basically redirects the invocation to a native function that
                // survives the script reloading, is much simpler, honestly.
                Script.bindWeak(globalThis, () => {
                    delegate.field("method_ptr").value = delegate.field("invoke_impl").value = Il2Cpp.api.domainGet;
                });
                Post.invoke(delegate, NULL);
            });
        }
        /** @internal */
        tryLocalValue(klass) {
            for (let i = 0; i < 16; i++) {
                const base = this.staticData.add(i * Process.pointerSize).readPointer();
                if (!base.isNull()) {
                    const object = new Il2Cpp.Object(base.readPointer()).asNullable();
                    if (object?.class?.isSubclassOf(klass, false)) {
                        return object;
                    }
                }
            }
        }
    }
    __decorate([
        lazy
    ], Thread.prototype, "internal", null);
    __decorate([
        lazy
    ], Thread.prototype, "isFinalizer", null);
    __decorate([
        lazy
    ], Thread.prototype, "managedId", null);
    __decorate([
        lazy
    ], Thread.prototype, "object", null);
    __decorate([
        lazy
    ], Thread.prototype, "staticData", null);
    __decorate([
        lazy
    ], Thread.prototype, "synchronizationContext", null);
    Il2Cpp.Thread = Thread;
    getter(Il2Cpp, "attachedThreads", () => {
        return readNativeList(Il2Cpp.api.threadGetAttachedThreads).map(_ => new Il2Cpp.Thread(_));
    });
    getter(Il2Cpp, "currentThread", () => {
        return new Il2Cpp.Thread(Il2Cpp.api.threadGetCurrent()).asNullable();
    });
    getter(Il2Cpp, "mainThread", () => {
        // I'm not sure if this is always the case. Typically, the main
        // thread managed id is 1, but this isn't always true: spawning
        // an Android application with Unity 5.3.8f1 will cause the Frida
        // thread to have the managed id equal to 1, whereas the main thread
        // managed id is 2.
        return Il2Cpp.attachedThreads[0];
    });
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    let Type = class Type extends NativeStruct {
        /** */
        static get enum() {
            const _ = (_, block = (_) => _) => block(Il2Cpp.corlib.class(_)).type.typeEnum;
            return {
                void: _("System.Void"),
                boolean: _("System.Boolean"),
                char: _("System.Char"),
                byte: _("System.SByte"),
                unsignedByte: _("System.Byte"),
                short: _("System.Int16"),
                unsignedShort: _("System.UInt16"),
                int: _("System.Int32"),
                unsignedInt: _("System.UInt32"),
                long: _("System.Int64"),
                unsignedLong: _("System.UInt64"),
                nativePointer: _("System.IntPtr"),
                unsignedNativePointer: _("System.UIntPtr"),
                float: _("System.Single"),
                double: _("System.Double"),
                pointer: _("System.IntPtr", _ => _.field("m_value")),
                valueType: _("System.Decimal"),
                object: _("System.Object"),
                string: _("System.String"),
                class: _("System.Array"),
                array: _("System.Void", _ => _.arrayClass),
                multidimensionalArray: _("System.Void", _ => new Il2Cpp.Class(Il2Cpp.api.classGetArrayClass(_, 2))),
                genericInstance: _("System.Int32", _ => _.interfaces.find(_ => _.name.endsWith("`1")))
            };
        }
        /** Gets the class of this type. */
        get class() {
            return new Il2Cpp.Class(Il2Cpp.api.typeGetClass(this));
        }
        /** */
        get fridaAlias() {
            function getValueTypeFields(type) {
                const instanceFields = type.class.fields.filter(_ => !_.isStatic);
                return instanceFields.length == 0 ? ["char"] : instanceFields.map(_ => _.type.fridaAlias);
            }
            if (this.isByReference) {
                return "pointer";
            }
            switch (this.typeEnum) {
                case Il2Cpp.Type.enum.void:
                    return "void";
                case Il2Cpp.Type.enum.boolean:
                    return "bool";
                case Il2Cpp.Type.enum.char:
                    return "uchar";
                case Il2Cpp.Type.enum.byte:
                    return "int8";
                case Il2Cpp.Type.enum.unsignedByte:
                    return "uint8";
                case Il2Cpp.Type.enum.short:
                    return "int16";
                case Il2Cpp.Type.enum.unsignedShort:
                    return "uint16";
                case Il2Cpp.Type.enum.int:
                    return "int32";
                case Il2Cpp.Type.enum.unsignedInt:
                    return "uint32";
                case Il2Cpp.Type.enum.long:
                    return "int64";
                case Il2Cpp.Type.enum.unsignedLong:
                    return "uint64";
                case Il2Cpp.Type.enum.float:
                    return "float";
                case Il2Cpp.Type.enum.double:
                    return "double";
                case Il2Cpp.Type.enum.nativePointer:
                case Il2Cpp.Type.enum.unsignedNativePointer:
                case Il2Cpp.Type.enum.pointer:
                case Il2Cpp.Type.enum.string:
                case Il2Cpp.Type.enum.array:
                case Il2Cpp.Type.enum.multidimensionalArray:
                    return "pointer";
                case Il2Cpp.Type.enum.valueType:
                    return this.class.isEnum ? this.class.baseType.fridaAlias : getValueTypeFields(this);
                case Il2Cpp.Type.enum.class:
                case Il2Cpp.Type.enum.object:
                case Il2Cpp.Type.enum.genericInstance:
                    return this.class.isStruct ? getValueTypeFields(this) : this.class.isEnum ? this.class.baseType.fridaAlias : "pointer";
                default:
                    return "pointer";
            }
        }
        /** Determines whether this type is passed by reference. */
        get isByReference() {
            return this.name.endsWith("&");
        }
        /** Determines whether this type is primitive. */
        get isPrimitive() {
            switch (this.typeEnum) {
                case Il2Cpp.Type.enum.boolean:
                case Il2Cpp.Type.enum.char:
                case Il2Cpp.Type.enum.byte:
                case Il2Cpp.Type.enum.unsignedByte:
                case Il2Cpp.Type.enum.short:
                case Il2Cpp.Type.enum.unsignedShort:
                case Il2Cpp.Type.enum.int:
                case Il2Cpp.Type.enum.unsignedInt:
                case Il2Cpp.Type.enum.long:
                case Il2Cpp.Type.enum.unsignedLong:
                case Il2Cpp.Type.enum.float:
                case Il2Cpp.Type.enum.double:
                case Il2Cpp.Type.enum.nativePointer:
                case Il2Cpp.Type.enum.unsignedNativePointer:
                    return true;
                default:
                    return false;
            }
        }
        /** Gets the name of this type. */
        get name() {
            const handle = Il2Cpp.api.typeGetName(this);
            try {
                return handle.readUtf8String();
            }
            finally {
                Il2Cpp.free(handle);
            }
        }
        /** Gets the encompassing object of the current type. */
        get object() {
            return new Il2Cpp.Object(Il2Cpp.api.typeGetObject(this));
        }
        /** Gets the type enum of the current type. */
        get typeEnum() {
            return Il2Cpp.api.typeGetTypeEnum(this);
        }
        /** */
        toString() {
            return this.name;
        }
    };
    __decorate([
        lazy
    ], Type.prototype, "class", null);
    __decorate([
        lazy
    ], Type.prototype, "fridaAlias", null);
    __decorate([
        lazy
    ], Type.prototype, "isByReference", null);
    __decorate([
        lazy
    ], Type.prototype, "isPrimitive", null);
    __decorate([
        lazy
    ], Type.prototype, "name", null);
    __decorate([
        lazy
    ], Type.prototype, "object", null);
    __decorate([
        lazy
    ], Type.prototype, "typeEnum", null);
    __decorate([
        lazy
    ], Type, "enum", null);
    Type = __decorate([
        recycle
    ], Type);
    Il2Cpp.Type = Type;
})(Il2Cpp || (Il2Cpp = {}));
var Il2Cpp;
(function (Il2Cpp) {
    class ValueType extends NativeStruct {
        type;
        constructor(handle, type) {
            super(handle);
            this.type = type;
        }
        /** Boxes the current value type in a object. */
        box() {
            return new Il2Cpp.Object(Il2Cpp.api.valueTypeBox(this.type.class, this));
        }
        /** Gets the field with the given name. */
        field(name) {
            return this.type.class.field(name).withHolder(this);
        }
        /** Gets the method with the given name. */
        method(name, parameterCount = -1) {
            return this.type.class.method(name, parameterCount).withHolder(this);
        }
        /** Gets the field with the given name. */
        tryField(name) {
            return this.type.class.tryField(name)?.withHolder(this);
        }
        /** Gets the field with the given name. */
        tryMethod(name, parameterCount = -1) {
            return this.type.class.tryMethod(name, parameterCount)?.withHolder(this);
        }
        /** */
        toString() {
            const ToString = this.method("ToString", 0);
            return this.isNull()
                ? "null"
                : // If ToString is defined within a value type class, we can
                    // avoid a boxing operation.
                    ToString.class.isValueType
                        ? ToString.invoke().content ?? "null"
                        : this.box().toString() ?? "null";
        }
    }
    Il2Cpp.ValueType = ValueType;
})(Il2Cpp || (Il2Cpp = {}));
/// <reference path="./utils/android.ts">/>
/// <reference path="./utils/console.ts">/>
/// <reference path="./utils/decorate.ts">/>
/// <reference path="./utils/getter.ts">/>
/// <reference path="./utils/lazy.ts">/>
/// <reference path="./utils/native-struct.ts">/>
/// <reference path="./utils/native-wait.ts">/>
/// <reference path="./utils/offset-of.ts">/>
/// <reference path="./utils/read-native-iterator.ts">/>
/// <reference path="./utils/read-native-list.ts">/>
/// <reference path="./utils/recycle.ts">/>
/// <reference path="./utils/unity-version.ts">/>
/// <reference path="./api.ts">/>
/// <reference path="./application.ts">/>
/// <reference path="./dump.ts">/>
/// <reference path="./exception-listener.ts">/>
/// <reference path="./filters.ts">/>
/// <reference path="./gc.ts">/>
/// <reference path="./memory.ts">/>
/// <reference path="./module.ts">/>
/// <reference path="./perform.ts">/>
/// <reference path="./tracer.ts">/>
/// <reference path="./structs/array.ts">/>
/// <reference path="./structs/assembly.ts">/>
/// <reference path="./structs/class.ts">/>
/// <reference path="./structs/delegate.ts">/>
/// <reference path="./structs/domain.ts">/>
/// <reference path="./structs/field.ts">/>
/// <reference path="./structs/gc-handle.ts">/>
/// <reference path="./structs/image.ts">/>
/// <reference path="./structs/memory-snapshot.ts">/>
/// <reference path="./structs/method.ts">/>
/// <reference path="./structs/object.ts">/>
/// <reference path="./structs/parameter.ts">/>
/// <reference path="./structs/pointer.ts">/>
/// <reference path="./structs/reference.ts">/>
/// <reference path="./structs/string.ts">/>
/// <reference path="./structs/thread.ts">/>
/// <reference path="./structs/type.ts">/>
/// <reference path="./structs/value-type.ts">/>
globalThis.Il2Cpp = Il2Cpp;
//# sourceMappingURL=index.js.map
;
/* QA-ONLY dispatcher. Never included in a game APK or server application.
 * Replaces repeated foreign-thread Thread.schedule metadata lookup with one
 * cached UnitySynchronizationContext.Post + one QA-owned delegate.
 */
(function(root) {
  'use strict';
  function fault(code) { const error=new Error(code);error.code=code;return error; }
  function createCore(adapter,options) {
    options=options||{};
    const later=options.setImmediate||setImmediate;
    const startTimer=options.setTimeout||setTimeout;
    const stopTimer=options.clearTimeout||clearTimeout;
    const timeout=options.timeoutMs||10000, batch=options.maxBatch||4;
    const identity=Object.freeze(Object.assign({},options.identity||{}));
    let state='NEW',binding=null,queue=[],posted=false,pumping=false,lastCode=null,sequence=0;
    const outstanding=new Set();
    const counts={enqueued:0,completed:0,rejected:0,postCalls:0,callbacks:0};
    function finish(ticket,ok,value) {
      if(ticket.settled)return;
      ticket.settled=true;ticket.action=null;stopTimer(ticket.timer);outstanding.delete(ticket);
      counts[ok?'completed':'rejected']++;
      // Promise continuations/RPC serialization do not execute inside managed
      // Post's native callback. The actions themselves must remain synchronous.
      later(function(){(ok?ticket.resolve:ticket.reject)(value);});
    }
    function poison(code) {
      if(state==='DISPOSED')return;
      state='POISONED';lastCode=code;
      const pending=Array.from(outstanding);queue=[];
      pending.forEach(function(ticket){finish(ticket,false,fault(code));});
    }
    function postIfNeeded() {
      if(state!=='READY'||posted||pumping||!queue.length)return;
      posted=true;counts.postCalls++;
      // This free attachment may still synchronize in the IL2CPP runtime. It
      // deliberately performs no method/class lookup or delegate construction.
      Promise.resolve().then(function(){return adapter.performFree(function(){
        if(state!=='READY')return;
        binding.postCached();
      });}).catch(function(){posted=false;poison('CACHED_POST_FAILED');});
    }
    function deliver() {
      counts.callbacks++;
      if(state!=='READY')return;
      try { binding.assertCurrentMain(); }
      catch(error) { poison(error&&error.code||'MAIN_BINDING_INVALID');return; }
      posted=false;
      if(pumping){poison('REENTRANT_MAIN_CALLBACK');return;}
      pumping=true;
      try {
        const work=queue.splice(0,batch);
        work.forEach(function(ticket){
          if(ticket.settled)return;
          if(state!=='READY'){finish(ticket,false,fault(lastCode||'DISPATCHER_NOT_READY'));return;}
          try {
            const value=ticket.action();
            if(value&&typeof value.then==='function'){
              finish(ticket,false,fault('ASYNC_UI_ACTION_FORBIDDEN'));
              poison('ASYNC_UI_ACTION_FORBIDDEN');
            } else finish(ticket,true,value);
          } catch(error) { finish(ticket,false,error); }
        });
      } finally { pumping=false; }
      postIfNeeded();
    }
    return {
      installOnCurrentMainThread:function(){
        if(state!=='NEW')throw fault('DISPATCHER_ALREADY_INSTALLED');
        state='INSTALLING';
        try {binding=adapter.bootstrapOnCurrentMain(deliver);state='READY';return this.status();}
        catch(error){state='POISONED';lastCode=error&&error.code||'BOOTSTRAP_FAILED';throw error;}
      },
      dispatch:function(action){
        if(state!=='READY')return Promise.reject(fault(lastCode||'DISPATCHER_NOT_READY'));
        if(typeof action!=='function'||action.constructor&&action.constructor.name==='AsyncFunction')return Promise.reject(fault('SYNC_READ_ONLY_ACTION_REQUIRED'));
        return new Promise(function(resolve,reject){
          const ticket={id:++sequence,action:action,resolve:resolve,reject:reject,settled:false,timer:null};
          ticket.timer=startTimer(function(){
            if(!ticket.settled){finish(ticket,false,fault('MAIN_CALLBACK_TIMEOUT'));poison('MAIN_CALLBACK_TIMEOUT');}
          },timeout);
          queue.push(ticket);outstanding.add(ticket);counts.enqueued++;postIfNeeded();
        });
      },
      invalidate:function(code){poison(code||'HOST_LIFECYCLE_INVALIDATED');},
      dispose:function(fromUnload){
        if(state==='DISPOSED')return {redirected:true,alreadyDisposed:true};
        poison('DISPATCHER_DISPOSED');
        let result;
        try { result=binding?binding.redirectAndRelease(!!fromUnload):{redirected:true,handlesFreed:0}; }
        catch(_) { result={redirected:false,needsOwnedProcessRestart:true,cleanupError:true}; }
        state=result.redirected?'DISPOSED':'POISONED';
        if(!result.redirected)lastCode='OWNED_PROCESS_RESTART_REQUIRED';
        return result;
      },
      status:function(){
        // PLAIN JS ONLY: no Process, Frida, Il2Cpp, pointer or NativeAPI reads.
        return {qaOnly:true,state:state,lastCode:lastCode,posted:posted,pumping:pumping,
          pending:outstanding.size,
          mainTid:binding?binding.mainTid:null,identity:Object.assign({},identity),counts:Object.assign({},counts)};
      }
    };
  }

  function createIl2CppAdapter(env,options) {
    options=options||{};
    const I=env.Il2Cpp,P=env.Process,S=env.Script,N=env.NULL;
    // Cache primitive identities ONCE, outside the public status handler.
    const identity={pid:P.id,architecture:P.arch,fridaVersion:env.Frida.version};
    let core;
    const adapter={
      performFree:function(block){return I.perform(block,'free');},
      bootstrapOnCurrentMain:function(deliver){
        const tid=P.getCurrentThreadId();
        if(!Number.isInteger(options.expectedMainTid)||options.expectedMainTid<=0||tid!==options.expectedMainTid)throw fault('BOOTSTRAP_NOT_ASSERTED_UNITY_MAIN');
        if(I.unityVersion!=='2018.4.23f1')throw fault('UNREVIEWED_UNITY_VERSION');
        const thread=I.currentThread;
        if(!thread||thread.id!==tid)throw fault('CURRENT_IL2CPP_THREAD_MISMATCH');
        // All reflection, execution-context discovery, method signature warming
        // and delegate allocation below occur only in this asserted main call.
        const context=thread.synchronizationContext;
        if(!context||context.isNull()||context.class.namespace+'.'+context.class.name!=='UnityEngine.UnitySynchronizationContext')throw fault('UNITY_CONTEXT_UNAVAILABLE');
        const post=context.method('Post',2);
        if(post.isStatic||post.isInflated||post.returnType.name!=='System.Void'||post.class.namespace+'.'+post.class.name!=='UnityEngine.UnitySynchronizationContext')throw fault('POST_ABI_UNSUPPORTED');
        const parameterNames=post.parameters.map(function(parameter){return parameter.type.name;});
        if(parameterNames[0]!=='System.Threading.SendOrPostCallback'||parameterNames[1]!=='System.Object')throw fault('POST_ABI_UNSUPPORTED');
        const signature=post.fridaSignature;
        if(signature.length!==3||signature.some(function(value){return value!=='pointer';}))throw fault('POST_ABI_UNSUPPORTED');
        // Cache this bound invoke closure, and warm its lazy method/type ABI
        // properties on main. No future call fetches context.method('Post').
        const postCachedInvoke=post.invoke;
        void post.nativeFunction;void post.returnType.typeEnum;void I.Type.enum;
        const contextGet=I.corlib.class('System.Threading.SynchronizationContext').method('get_Current',0);
        if(!contextGet.isStatic||contextGet.isInflated)throw fault('CONTEXT_GET_ABI_UNSUPPORTED');
        const getCurrentCached=contextGet.invoke.bind(contextGet);
        void contextGet.nativeFunction;void contextGet.returnType.typeEnum;
        const actualCurrent=getCurrentCached();
        if(!actualCurrent||!actualCurrent.handle.equals(context.handle))throw fault('UNITY_CURRENT_CONTEXT_MISMATCH');
        const domainGet=I.api.domainGet,getTarget=I.api.gcHandleGetTarget,freeHandle=I.api.gcHandleFree;
        const domain=domainGet();
        const callbackClass=I.corlib.class('System.Threading.SendOrPostCallback');
        const delegate=I.delegate(callbackClass,function(){deliver();});
        // Pinned strong handles protect exact cached object pointers. Fixed
        // count per observer: one context + one delegate; no per-action handle.
        let contextRef=null,delegateRef=null,binding=null;
        try {
        delegateRef=delegate.ref(true);contextRef=context.ref(true);
        const methodPointer=delegate.field('method_ptr'),invokePointer=delegate.field('invoke_impl');
        const methodSlot=delegate.handle.add(methodPointer.offset),invokeSlot=delegate.handle.add(invokePointer.offset);
        const delegatePointer=delegate.handle,contextPointer=context.handle;
        const callbackKey=delegatePointer.toString();
        let redirected=false;
        binding={mainTid:tid,
          postCached:function(){postCachedInvoke(delegate,N);},
          assertCurrentMain:function(){
            if(P.getCurrentThreadId()!==tid)throw fault('CALLBACK_WRONG_NATIVE_THREAD');
            if(!domainGet().equals(domain))throw fault('DOMAIN_CHANGED');
            const now=getCurrentCached();
            if(!now||!now.handle.equals(contextPointer))throw fault('UNITY_CONTEXT_REPLACED');
          },
          redirectAndRelease:function(fromUnload){
            if(redirected)return {redirected:true,handlesFreed:0};
            // All pointers/API callables were cached on main. If ownership is
            // not provable, never write potentially recycled memory. The host
            // must force-stop its owned game process before unloading/retry.
            if(!domainGet().equals(domain)||!getTarget(delegateRef.handle).equals(delegatePointer)||!getTarget(contextRef.handle).equals(contextPointer))return {redirected:false,needsOwnedProcessRestart:true};
            // Only our QA-created delegate is modified. This is the bridge's
            // 0.9.1 unload tombstone: stable native domain_get ignores surplus
            // args; its pointer return is ignored by void SendOrPostCallback.
            methodSlot.writePointer(domainGet);invokeSlot.writePointer(domainGet);
            redirected=true;
            freeHandle(delegateRef.handle);freeHandle(contextRef.handle);
            delete I._callbacksToKeepAlive[callbackKey];
            return {redirected:true,handlesFreed:2,fromUnload:fromUnload};
          }};
        S.bindWeak(env.weakTarget||root,function(){if(core)core.dispose(true);});
        // Warm all conversions/ABI caches through one empty QA callback post.
        // It can run later; it performs no game callback or player-state write.
        postCachedInvoke(delegate,N);
        return binding;
        } catch(error) {
          // No partially initialized pinned handles or posted callback may be
          // silently abandoned. Before first Post, only these owned handles
          // exist; after Post, redirect through the completed binding first.
          if(binding)binding.redirectAndRelease(false);
          else {if(delegateRef)freeHandle(delegateRef.handle);if(contextRef)freeHandle(contextRef.handle);}
          throw error;
        }
      }
    };
    core=createCore(adapter,Object.assign({},options,{identity:identity}));
    return core;
  }
  const exports={createCore:createCore,createIl2CppAdapter:createIl2CppAdapter};
  if(typeof module!=='undefined'&&module.exports)module.exports=exports;
  else root.CachedMainThreadDispatcher=exports;
})(typeof globalThis!=='undefined'?globalThis:this);

;
/* Disposable runtime QA observer. No APK patch, game-state setter or UI click.
 * Prepend frida-il2cpp-bridge 0.9.1 dist/index.js before loading in Frida 16.6.6.
 * All Unity object reads run on the Unity main thread; taps belong to adb.
 */
(function () {
  "use strict";
  var ready = false, lastError = "", runtime = {}, classCache = {}, initPending = false;
  var BRIDGE_VERSION = "0.9.1", AGENT_VERSION = 8;
  var QA_IDENTITY = {pid:Process.id,architecture:Process.arch,fridaVersion:Frida.version};
  var TEXT_TYPES = ["UnityEngine.UI.Text", "TMPro.TMP_Text", "Jigbox.Components.TextView", "LLAS.Components.UI.ProductTextView"];
  var DEFAULT_TYPES = ["UnityEngine.UI.Button", "UnityEngine.UI.Toggle", "UnityEngine.UI.InputField", "TMPro.TMP_InputField", "UnityEngine.UI.ScrollRect"].concat(TEXT_TYPES);

  function exists(value) { return !!value && !(typeof value.isNull === "function" && value.isNull()); }
  function text(value) { return exists(value) ? String(value.content === undefined ? value : value.content || "") : ""; }
  function call(object, name, args) { return object.method(name, (args || []).length).invoke.apply(object.method(name, (args || []).length), args || []); }
  function maybe(object, name, fallback, args) { try { return exists(object) ? call(object, name, args) : fallback; } catch (_) { return fallback; } }
  function findClass(name, optional) {
    if (classCache[name] !== undefined) return classCache[name];
    var assemblies = Il2Cpp.domain.assemblies;
    for (var i = 0; i < assemblies.length; i++) {
      var candidate = assemblies[i].image.tryClass(name);
      if (candidate) { classCache[name] = candidate; return candidate; }
    }
    if (optional) { classCache[name] = null; return null; }
    throw new Error("Unity class is unavailable: " + name);
  }
  function overloaded(object, name, parameterTypes, args) {
    return object.method(name, parameterTypes.length).overload.apply(object.method(name, parameterTypes.length), parameterTypes).invoke.apply(
      object.method(name, parameterTypes.length).overload.apply(object.method(name, parameterTypes.length), parameterTypes), args);
  }
  function nullObject() { return new Il2Cpp.Object(ptr(0)); }
  function vector(klass, x, y) {
    var memory = Memory.alloc(klass.valueTypeSize);
    var value = new Il2Cpp.ValueType(memory, klass.type);
    value.field("x").value = x; value.field("y").value = y;
    return value;
  }
  function field(value, name) { return Number(value.field(name).value); }
  function gameObject(component) { return maybe(component, "get_gameObject", null) || component; }
  function transform(component) { return maybe(component, "get_transform", null); }
  function component(object, klass) {
    if (!exists(object) || !klass) return null;
    try { var result = overloaded(object, "GetComponent", ["System.Type"], [klass.type.object]); return exists(result) ? result : null; } catch (_) { return null; }
  }
  function fullType(object) { return object.class.namespace ? object.class.namespace + "." + object.class.name : object.class.name; }
  function instanceId(object) { return maybe(object, "GetInstanceID", object.handle.toString()); }
  function hierarchy(tr) {
    var parts = [], seen = {}, count = 0;
    while (exists(tr) && count++ < 64) {
      var key = tr.handle.toString(); if (seen[key]) break; seen[key] = true;
      parts.push(text(maybe(tr, "get_name", null)) || "?"); tr = maybe(tr, "get_parent", null);
    }
    return parts.reverse().join("/");
  }
  function active(componentObject) {
    var go = gameObject(componentObject);
    return { gameObject: go, active: !!maybe(go, "get_activeInHierarchy", false),
      enabled: maybe(componentObject, "get_isActiveAndEnabled", maybe(componentObject, "get_enabled", true)) !== false };
  }
  function interactable(object) {
    var value = maybe(object, "IsInteractable", null);
    return value === null ? maybe(object, "get_interactable", null) : !!value;
  }
  function nearestSelectable(tr) {
    var count = 0;
    while (exists(tr) && count++ < 48) {
      var selected = component(gameObject(tr), runtime.selectable);
      if (exists(selected)) return selected;
      tr = maybe(tr, "get_parent", null);
    }
    return null;
  }
  function nearestInput(tr) {
    var count = 0;
    while (exists(tr) && count++ < 32) {
      var input = component(gameObject(tr), runtime.inputField) || component(gameObject(tr), runtime.tmpInputField);
      if (exists(input)) return input;
      tr = maybe(tr, "get_parent", null);
    }
    return null;
  }
  function inputDescription(input, numericTestId) {
    var raw = text(maybe(input, "get_text", null)), type = Number(maybe(input, "get_inputType", -1));
    var content = Number(maybe(input, "get_contentType", -1));
    var password = type === 2 || content === 7 || content === 8;
    var allowed = !password && /^\d{1,12}$/.test(raw) && raw === String(numericTestId || "893611090");
    return { value: allowed ? raw : null, length: raw.length, redacted: !allowed && raw.length > 0,
      password: password, focused: !!maybe(input, "get_isFocused", false), readOnly: !!maybe(input, "get_readOnly", false),
      characterLimit: Number(maybe(input, "get_characterLimit", 0)), inputType: type, contentType: content };
  }
  function redactInputText(value, input, description) {
    if (!exists(input) || !description || !description.redacted) return value;
    var raw = text(maybe(input, "get_text", null));
    return raw ? String(value).split(raw).join("[redacted input]") : value;
  }
  function canvasFor(tr) {
    var count = 0, result = null;
    while (exists(tr) && count++ < 48) {
      var canvas = component(gameObject(tr), runtime.canvas);
      if (exists(canvas)) { result = canvas; break; }
      tr = maybe(tr, "get_parent", null);
    }
    if (!result) throw new Error("No Canvas ancestor for this UI object");
    var mode = Number(call(result, "get_renderMode")), camera = nullObject();
    if (mode !== 0) {
      camera = maybe(result, "get_worldCamera", null);
      if (!exists(camera)) camera = maybe(runtime.camera, "get_main", null);
      if (!exists(camera)) throw new Error("Camera/world-space Canvas has no projection camera");
    }
    return { object: result, mode: mode, camera: camera, cameraName: exists(camera) ? text(maybe(camera, "get_name", null)) : null };
  }
  function rawRect(tr, canvas, screen) {
    var corners = Il2Cpp.array(runtime.vector3, 4);
    call(tr, "GetWorldCorners", [corners]);
    var points = [];
    for (var i = 0; i < 4; i++) {
      var projected = runtime.rectUtility.method("WorldToScreenPoint", 2).invoke(canvas.camera, corners.get(i));
      points.push({ x: field(projected, "x"), y: screen.height - field(projected, "y") });
    }
    var xs = points.map(function (p) { return p.x; }), ys = points.map(function (p) { return p.y; });
    var result = { left: Math.min.apply(null, xs), top: Math.min.apply(null, ys), right: Math.max.apply(null, xs), bottom: Math.max.apply(null, ys) };
    if (![result.left, result.top, result.right, result.bottom].every(Number.isFinite)) throw new Error("Non-finite projected RectTransform");
    result.width = result.right - result.left; result.height = result.bottom - result.top;
    return result;
  }
  function intersect(a, b) { return { left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) }; }
  function rectAndClipping(tr, screen) {
    var canvas = canvasFor(tr), original = rawRect(tr, canvas, screen);
    var clipped = intersect(original, { left: 0, top: 0, right: screen.width, bottom: screen.height });
    var parent = tr, count = 0, alpha = 1, groupsInteractable = true, blocksRaycasts = true, ignoreParentGroups = false;
    while (exists(parent) && count++ < 48) {
      var go = gameObject(parent), group = component(go, runtime.canvasGroup);
      if (!ignoreParentGroups && exists(group) && maybe(group, "get_enabled", true)) {
        alpha *= Number(maybe(group, "get_alpha", 1));
        groupsInteractable = groupsInteractable && maybe(group, "get_interactable", true) !== false;
        blocksRaycasts = blocksRaycasts && maybe(group, "get_blocksRaycasts", true) !== false;
        ignoreParentGroups = !!maybe(group, "get_ignoreParentGroups", false);
      }
      if (parent !== tr) {
        var mask = component(go, runtime.rectMask) || component(go, runtime.mask);
        if (exists(mask) && maybe(mask, "get_isActiveAndEnabled", true)) {
          try { clipped = intersect(clipped, rawRect(parent, canvas, screen)); } catch (_) { /* Native hit test remains authoritative. */ }
        }
      }
      parent = maybe(parent, "get_parent", null);
    }
    clipped.width = Math.max(0, clipped.right - clipped.left); clipped.height = Math.max(0, clipped.bottom - clipped.top);
    return { bounds: original, visibleBounds: clipped,
      center: { x: Math.max(0, Math.min(screen.width - 1, Math.round((clipped.left + clipped.right) / 2))),
        y: Math.max(0, Math.min(screen.height - 1, Math.round((clipped.top + clipped.bottom) / 2))) },
      visible: clipped.width >= 1 && clipped.height >= 1 && alpha > .001,
      alpha: alpha, groupsInteractable: groupsInteractable, blocksRaycasts: blocksRaycasts,
      canvas: { mode: canvas.mode, camera: canvas.cameraName } };
  }
  function componentText(object) {
    var getters = ["get_text", "get_Text", "get_SourceText", "get_RawText", "get_TextSource", "get_TextContent"];
    for (var i = 0; i < getters.length; i++) {
      var value = null;
      try {
        var getter = object.method(getters[i], 0), owner = getter.class.namespace || "";
        // Game caption implementations may have side effects. Read their string
        // fields below; only Unity/TMP's ordinary UI getters are invoked here.
        if (!/^(?:UnityEngine(?:\.|$)|TMPro$)/.test(owner)) continue;
        value = getter.invoke();
      } catch (_) { continue; }
      if (typeof value === "string" && value.trim()) return value.trim();
      if (exists(value) && typeof value.content === "string" && value.content.trim()) return value.content.trim();
    }
    // Custom LLAS/Jigbox captions are not UnityEngine.UI.Text. Read only
    // existing string fields; never invoke setters, events or game callbacks.
    var klass = object.class, depth = 0;
    while (klass && depth++ < 5) {
      var fields = klass.fields.filter(function (entry) { return entry.type.name === "System.String" && /^(?:m_)?_?(?:text|sourceText|textSource|rawText|content)$/i.test(entry.name); });
      for (var j = 0; j < fields.length; j++) {
        try { var content = object.field(fields[j].name).value; if (exists(content) && typeof content.content === "string" && content.content.trim()) return content.content.trim(); } catch (_) {}
      }
      klass = klass.parent;
    }
    return "";
  }
  function descendantText(object) {
    var values = [];
    runtime.textClasses.forEach(function (klass) {
      if (!klass) return;
      try {
        var children = overloaded(object, "GetComponentsInChildren", ["System.Type", "System.Boolean"], [klass.type.object, false]);
        for (var i = 0; i < children.length && values.length < 24; i++) {
          var child = children.get(i); if (!active(child).active) continue;
          var value = componentText(child);
          if (value && values.indexOf(value) < 0) values.push(value);
        }
      } catch (_) { /* Report object name when its text component is custom. */ }
    });
    return values.join(" | ");
  }
  function allOfType(klass) {
    try { return overloaded(runtime.resources, "FindObjectsOfTypeAll", ["System.Type"], [klass.type.object]); }
    catch (_) { return overloaded(runtime.unityObject, "FindObjectsOfType", ["System.Type"], [klass.type.object]); }
  }
  function numericField(object, name) {
    try {
      var value = object.field(name).value;
      if (typeof value === "number") return Number.isFinite(value) ? value : null;
      if (value && typeof value.field === "function") return Number(value.field("value__").value);
    } catch (_) {}
    return null;
  }
  function nativeFeatureState() {
    var bridge = Process.findModuleByName("libfovmod.so"), game = Process.findModuleByName("libil2cpp.so");
    var result = { bridgeLoaded: !!bridge, gameLoaded: !!game, config: null };
    if (game) {
      var ranges = game.enumerateRanges("rw-");
      for (var i = 0; i < ranges.length; i++) {
        try {
          var p = ranges[i].base;
          if (ranges[i].size < 32 || p.readUtf8String(8) !== "SFOVRW22") continue;
          if (p.add(8).readU32() !== 1 || p.add(12).readU32() !== 32) continue;
          result.config = { magic: "SFOVRW22", version: 1, size: 32,
            min: p.add(16).readFloat(), max: p.add(20).readFloat(),
            fastIntro: p.add(24).readU32(), generation: p.add(28).readU32(),
            writable: ranges[i].protection.indexOf("w") >= 0,
            executable: ranges[i].protection.indexOf("x") >= 0 };
          break;
        } catch (_) {}
      }
    }
    // Read platform-owned getters only; no game setters or callbacks are called.
    try {
      if (typeof Java !== "undefined" && Java.available) Java.performNow(function () {
        var activity = Java.use("com.unity3d.player.UnityPlayer").currentActivity.value;
        if (activity) {
          var preference = Number(activity.getSharedPreferences("fovmod", 0).getInt("orient", 0));
          result.requestedOrientation = Number(activity.getRequestedOrientation());
          if (result.config) result.config.orientation = preference;
        }
      });
    } catch (error) { result.platformReadError = String(error); }
    return result;
  }
// Optional fragment for the existing, main-thread, read-only Unity observer.
// Uses its existing findClass/allOfType/exists/active/maybe/instanceId helpers.
// No game actions, setters, callbacks, scene changes, or player-state writes.
function mvReadField(object, name) {
  if (!object || (object.handle && object.handle.isNull())) return null;
  try { var value = object.field(name).value; return value && value.handle && value.handle.isNull() ? null : value; } catch (_) { return null; }
}
function mvBacking(object, name) { return mvReadField(object, "<" + name + ">k__BackingField"); }
function mvNumber(value) {
  if (value === null || value === undefined) return null;
  var n = Number(value); return Number.isFinite(n) ? n : null;
}
function mvExistingComponentInfo(object) {
  var tr = transform(object), position = maybe(tr, "get_position", null);
  var info = { id: String(instanceId(object)), gameObjectId: String(instanceId(gameObject(object))),
    path: hierarchy(tr), active: active(object).active };
  if (position) info.position = {x: field(position,"x"), y: field(position,"y"), z: field(position,"z")};
  return info;
}
// Read-only additions to mv_observer.fragment.js; same Unity main-thread observer.
// GL/JP metadata verified. No game actions, callbacks, setters, or state writes.
function observeExistingMvExtras(screen,raycaster) {
  var result = { deckRoots: [], suitPickerCells: [], directorAssets: [], errors: [] };
  function collect(type, callback) {
    var klass = findClass(type, true);
    if (!klass) { result.errors.push({type:type,error:"Type absent"}); return; }
    try {
      var objects=allOfType(klass);
      for (var i=0;i<objects.length && i<128;i++) {
        var object=objects.get(i);
        if (exists(object) && active(object).active) callback(object);
      }
    } catch(error) { result.errors.push({type:type,error:String(error)}); }
  }
  collect("LLAS.Scene.LiveMvDeckSelect.LiveMvDeckSelectRoot", function(object) {
    var vo=mvReadField(object,"liveMvDeckSelectVO"),info=mvExistingComponentInfo(object);
    info.liveMasterId=mvNumber(mvBacking(vo,"LiveMasterId"));
    info.standingMemberNum=mvNumber(mvBacking(vo,"StandingMemberNum"));
    info.voClass=vo?fullType(vo):null;
    result.deckRoots.push(info);
  });
  collect("LLAS.SuitChangePopupSuitTileViewCell", function(object) {
    var vo=mvReadField(object,"memberSuitVO"),info=mvExistingComponentInfo(object);
    info.memberId=mvNumber(mvBacking(vo,"MemberMasterId"));
    info.suitId=mvNumber(mvBacking(vo,"MasterId"));
    info.voClass=vo?fullType(vo):null;
    // MemberSuitVO has no IsUnlocked field. Actual active/hittable button and
    // observed successful resulting deck change establish selectability.
    var button=mvReadField(object,"button");
    if(exists(button)) {info.button={id:String(instanceId(button)),path:hierarchy(transform(button)),type:fullType(button)};info.target=mvUiTarget(button,screen,raycaster);}
    result.suitPickerCells.push(info);
  });
  collect("LLAS.Scene.Live.LiveDirector", function(object) {
    var asset=mvReadField(object,"asset"),members=mvBacking(asset,"Members"),info=mvExistingComponentInfo(object);
    info.assetClass=asset?fullType(asset):null;info.members=[];
    // Live3DAssetVO retains the asset VOs; actual instantiated model identity
    // is separately observed via LiveCoreMember + its formation position.
    if(members && typeof members.length === "number") {
      for(var i=0;i<members.length && i<12;i++) {
        var vo=members.get(i),nullable=mvBacking(vo,"SuitId"),suitId=null;
        // System.Nullable<Int32> fields, read only; a missing value stays null.
        try { if(nullable.field("has_value").value===true) suitId=mvNumber(nullable.field("value").value); } catch(_) {}
        info.members.push({memberId:mvNumber(mvBacking(vo,"MemberMasterId")),
          formationPosition:mvNumber(mvBacking(vo,"FormationPosition")),suitId:suitId,voClass:vo?fullType(vo):null});
      }
    }
    result.directorAssets.push(info);
  });
  return result;
}

// Optional read-only MV music/tab observation; GL/JP field names verified.
// Requires the helpers of mv_observer.fragment.js. No actions/callbacks/setters.
function observeExistingMusicRowsAndMvTabs(screen,raycaster) {
  var result={musicRows:[],musicSelection:[],deckTabGroups:[],errors:[]};
  function collect(type,callback) {
    var klass=findClass(type,true);
    if(!klass){result.errors.push({type:type,error:"Type absent"});return;}
    try{var objects=allOfType(klass);for(var i=0;i<objects.length&&i<128;i++){
      var object=objects.get(i);if(exists(object)&&active(object).active)callback(object);
    }}catch(error){result.errors.push({type:type,error:String(error)});}
  }
  collect("LLAS.Scene.LiveMusicSelect.LiveMusicSelectScrollCell",function(object){
    var vo=mvBacking(object,"CellVO"),info=mvExistingComponentInfo(object);
    info.liveMasterId=mvNumber(mvBacking(vo,"LiveMasterId"));
    info.isPlayable=mvBacking(vo,"IsPlayable");
    info.voClass=vo?fullType(vo):null;
    // This cell has no button field. Its existing GameObject/component path
    // and actual jacket/title graphics identify its real visible pointer area.
    // Use only the observer's current projected and raycast-tested hit bounds;
    // do not invent a callback, button reference, or fixed coordinate.
    ["jacket","title"].forEach(function(key){var component=mvReadField(object,key);
      if(exists(component))info[key]={id:String(instanceId(component)),path:hierarchy(transform(component)),type:fullType(component)};
    });
    info.target=mvUiTarget(object,screen,raycaster);
    result.musicRows.push(info);
  });
  // Static GL metadata SHA256 c1ac82ff0b68351ffb3a58fce275b940c26316da64cdfc8201413382afdec14f:
  // both fields reference LLAS.DM.LiveMusicSelectDM+CellVO. Record their
  // independent existing IDs; neither field implies timing or MV readiness.
  collect("LLAS.Scene.LiveMusicSelect.LiveMusicSelectController",function(object){
    var info=mvExistingComponentInfo(object);
    ["currentSelectedCellVO","decidedCellVO"].forEach(function(key){
      var vo=mvReadField(object,key);
      info[key]={liveMasterId:mvNumber(mvBacking(vo,"LiveMasterId")),
        isPlayable:mvBacking(vo,"IsPlayable"),voClass:vo?fullType(vo):null};
    });
    info.noteInputBlocker=nativeMusicBlocker(object);
    result.musicSelection.push(info);
  });
  collect("LLAS.Components.UI.LiveMvDeckTabGroup",function(object){
    var info=mvExistingComponentInfo(object),vos=mvReadField(object,"deckTabVOs"),group=mvReadField(object,"deckSwitchToggleGroup");
    var list=mvReadField(group,"toggles"),items=mvReadField(list,"_items"),size=mvNumber(mvReadField(list,"_size"));
    info.selectedDeckIndex=mvNumber(mvReadField(object,"selectedDeckIndex"));info.tabs=[];
    if(vos&&typeof vos.length==="number")for(var i=0;i<vos.length&&i<8;i++){
      var vo=vos.get(i),entry={index:i,liveMasterId:mvNumber(mvBacking(vo,"LiveMasterId")),deckType:mvNumber(mvBacking(vo,"LiveMvDeckType"))};
      // Existing Setup/OnClickDeckSwitchButton consumes this matching tab index.
      // Record actual referenced toggles, then verify resulting deck VO class.
      if(items&&typeof items.length==="number"&&size!==null&&i<size&&i<items.length){
        var toggle=items.get(i),button=mvReadField(toggle,"button");
        if(exists(toggle))entry.toggle={id:String(instanceId(toggle)),path:hierarchy(transform(toggle)),isOn:mvReadField(toggle,"isOn")};
        if(exists(button)){entry.button={id:String(instanceId(button)),path:hierarchy(transform(button)),type:fullType(button)};entry.target=mvUiTarget(button,screen,raycaster);}
      }
      info.tabs.push(entry);
    }
    result.deckTabGroups.push(info);
  });
  return result;
}

// R8 QA-only prospective native hit model. These helpers never dispatch an
// event, invoke game selection methods, or mutate an existing game object.
function nativeMusicBounds(position,size,lossyScale,pivot) {
  function number(value) { if(typeof value!=="number" || !Number.isFinite(value))throw new Error("Unreadable native music geometry");return Math.fround(value); }
  var x=number(position.x),y=number(position.y),z=number(position.z);
  var width=Math.fround(number(size.x)*number(lossyScale.x)),height=Math.fround(number(size.y)*number(lossyScale.y));
  var px=number(pivot.x),py=number(pivot.y);
  return {min:{x:Math.fround(x-Math.fround(width*px)),y:Math.fround(y-Math.fround(height*py)),z:z},
    max:{x:Math.fround(x+Math.fround(width*Math.fround(1-px))),y:Math.fround(y+Math.fround(height*Math.fround(1-py))),z:z}};
}
function nativeMusicReadableBounds(bounds) {
  return !!bounds && ["min","max"].every(function(side){return bounds[side] && ["x","y","z"].every(function(axis){return typeof bounds[side][axis]==="number" && Number.isFinite(bounds[side][axis]);});});
}
function nativeMusicContains(bounds,point) {
  return nativeMusicReadableBounds(bounds) && ["x","y","z"].every(function(axis){
    return typeof point[axis]==="number" && Number.isFinite(point[axis]) && Math.fround(point[axis])>=bounds.min[axis] && Math.fround(point[axis])<=bounds.max[axis];
  });
}
function nativeMusicBoundedCells(size,capacity,readEntry) {
  var result={complete:false,reason:null,limit:512,size:size,capacity:capacity,entries:[]};
  if(!Number.isInteger(size)||size<1||size>512||!Number.isInteger(capacity)||capacity<size){result.reason="Native managed-cell storage is incomplete or exceeds512";return result;}
  for(var i=0;i<size;i++) {
    var entry;
    try{entry=readEntry(i);}catch(error){result.reason="Unreadable native managed-cell entry at ordinal"+i+": "+String(error);return result;}
    if(!entry || !nativeMusicReadableBounds(entry.nativeBounds)){result.reason="Unreadable native bounds at ordinal"+i;return result;}
    result.entries.push(entry);
  }
  result.complete=true;return result;
}
function nativeMusicFirstContaining(entries,point) {
  for(var i=0;i<entries.length;i++)if(nativeMusicContains(entries[i].nativeBounds,point))return entries[i];
  return null;
}
function nativeMusicCellIdentity(entry) {
  if(!entry)return null;
  var result={};["ordinal","index","positionIndex","rectId","cellId","liveMasterId","activeInHierarchy"].forEach(function(key){result[key]=entry[key];});return result;
}
function nativeMusicScan(entries,intended,point) {
  if(entries.some(function(entry){return !entry||!nativeMusicReadableBounds(entry.nativeBounds);}))return {qualified:false,firstContaining:null,reason:"Native managed-cell geometry is incomplete; no skipped entry"};
  var first=nativeMusicFirstContaining(entries,point),result={qualified:false,firstContaining:nativeMusicCellIdentity(first)};
  if(!first)return Object.assign(result,{reason:"No native managed-cell bounds contain the prospective point"});
  if(first.activeInHierarchy!==true)return Object.assign(result,{reason:"FIRST native containing cell is inactive; no later-cell fallback"});
  if(["ordinal","index","positionIndex","rectId","cellId","liveMasterId"].some(function(key){return first[key]!==intended[key];}))return Object.assign(result,{reason:"FIRST native containing cell differs from intended typed music cell"});
  return Object.assign(result,{qualified:true,reason:"FIRST native containing cell is the intended active typed cell"});
}
function nativeMusicObject(object) {
  if(!exists(object))return null;
  return {id:String(instanceId(object)),type:fullType(object),path:hierarchy(transform(object))};
}
function nativeMusicBlocker(controller) {
  var result={resolved:false,id:null,path:null,activeSelf:null,activeInHierarchy:null,error:null};
  try {
    var blocker=mvReadField(controller,"noteInputBlocker");
    if(!exists(blocker)){result.error="Controller noteInputBlocker unavailable";return result;}
    result.id=String(instanceId(blocker));result.path=hierarchy(transform(blocker));
    result.activeSelf=call(blocker,"get_activeSelf");result.activeInHierarchy=call(blocker,"get_activeInHierarchy");
    result.resolved=typeof result.activeSelf==="boolean" && typeof result.activeInHierarchy==="boolean";
    if(!result.resolved)result.error="Controller noteInputBlocker active state unreadable";
  }catch(error){result.error=String(error);}
  return result;
}
function nativeMusicEventCamera(module) {
  var result={proof:{resolved:false,isNull:null,id:null,path:null,error:null},camera:null};
  try {
    if(!exists(module))throw new Error("Current first raycast module unavailable");
    var getter=module.method("get_eventCamera",0);
    if(!/^UnityEngine(?:\.|$)/.test(getter.class.namespace||""))throw new Error("Non-Unity eventCamera getter is not invoked");
    var camera=getter.invoke();result.proof.resolved=true;result.proof.isNull=!exists(camera);
    result.camera=exists(camera)?camera:nullObject();
    if(exists(camera)){result.proof.id=String(instanceId(camera));result.proof.path=hierarchy(transform(camera));}
  }catch(error){result.proof.error=String(error);}
  return result;
}
function nativeMusicVector(value,axes) {
  var result={};axes.forEach(function(axis){var number=field(value,axis);if(!Number.isFinite(number))throw new Error("Non-finite native geometry");result[axis]=Math.fround(number);});return result;
}
function nativeMusicRect(rect) {
  var tr=transform(rect),position=nativeMusicVector(call(tr,"get_position"),["x","y","z"]);
  var scale=nativeMusicVector(call(tr,"get_lossyScale"),["x","y","z"]),pivot=nativeMusicVector(call(rect,"get_pivot"),["x","y"]);
  var local=call(rect,"get_rect"),size=nativeMusicVector(call(local,"get_size"),["x","y"]);
  var rotation=nativeMusicVector(call(tr,"get_rotation"),["x","y","z","w"]);
  return {rectId:String(instanceId(rect)),path:hierarchy(tr),position:position,lossyScale:scale,pivot:pivot,size:size,rotation:rotation,
    nativeBounds:nativeMusicBounds(position,size,scale,pivot)};
}
function nativeMusicStateVector(object,name) {
  try{var value=mvReadField(object,name);return value?nativeMusicVector(value,["x","y"]):null;}catch(_){return null;}
}
function nativeMusicCanvasCamera(view) {
  var tr=transform(view),count=0;
  while(exists(tr)&&count++<48) {
    var canvas=component(gameObject(tr),runtime.canvas);
    if(exists(canvas)) {
      if(Number(call(canvas,"get_renderMode"))===0)return nullObject();
      var camera=call(canvas,"get_worldCamera");
      if(!exists(camera))throw new Error("Native viewport Canvas camera unresolved; no Camera.main fallback");
      return camera;
    }
    tr=maybe(tr,"get_parent",null);
  }
  throw new Error("Native viewport Canvas unavailable");
}
function nativeMusicViewport(view,screen,camera) {
  var tr=transform(view),original=rawRect(tr,{camera:camera},screen);
  var clipped=intersect(original,{left:0,top:0,right:screen.width,bottom:screen.height});
  var parent=tr,count=0,alpha=1,groupsInteractable=true,blocksRaycasts=true,ignore=false;
  while(exists(parent)&&count++<48) {
    var go=gameObject(parent),group=component(go,runtime.canvasGroup);
    if(!ignore&&exists(group)&&maybe(group,"get_enabled",true)) {
      alpha*=Number(call(group,"get_alpha"));groupsInteractable=groupsInteractable&&call(group,"get_interactable")!==false;
      blocksRaycasts=blocksRaycasts&&call(group,"get_blocksRaycasts")!==false;ignore=!!call(group,"get_ignoreParentGroups");
    }
    if(parent!==tr) {
      var mask=component(go,runtime.rectMask)||component(go,runtime.mask);
      if(exists(mask)&&maybe(mask,"get_isActiveAndEnabled",true))clipped=intersect(clipped,rawRect(parent,{camera:camera},screen));
    }
    parent=maybe(parent,"get_parent",null);
  }
  clipped.width=Math.max(0,clipped.right-clipped.left);clipped.height=Math.max(0,clipped.bottom-clipped.top);
  return {bounds:original,visibleBounds:clipped,visible:clipped.width>=1&&clipped.height>=1&&alpha>.001,
    alpha:alpha,groupsInteractable:groupsInteractable,blocksRaycasts:blocksRaycasts};
}
function observeNativeMusicSelection(screen,rows) {
  var result={proof:{schema:1,complete:false,reason:null,scope:"PROSPECTIVE_NATIVE_HIT_PREDICTION",owners:[]},owners:[]};
  if(screen.scene!=="LiveMusicSelect"){result.proof.reason="Native music selection is outside LiveMusicSelect";return result;}
  try {
    var klass=findClass("LLAS.Components.UI.ProductMusicScrollView",true);
    if(!klass)throw new Error("ProductMusicScrollView metadata unavailable");
    var objects=allOfType(klass),candidates=[];
    if(objects.length>32)throw new Error("Native scroll ownership enumeration exceeds32");
    for(var i=0;i<objects.length && i<32;i++) {
      var view=objects.get(i);if(!exists(view)||!active(view).active)continue;
      var geometry=nativeMusicViewport(view,screen,nativeMusicCanvasCamera(view));if(!geometry.visible)continue;
      candidates.push({view:view,geometry:geometry});
    }
    if(candidates.length!==1)throw new Error("Native music scroll ownership is absent or ambiguous");
    var current=candidates[0],view=current.view,model=mvReadField(view,"model"),proxy=mvReadField(view,"inputProxy"),transition=mvReadField(view,"transition");
    if(!exists(model)||!exists(proxy)||!exists(transition))throw new Error("Owned native model/inputProxy/transition reference unavailable");
    if(!descendsFrom(gameObject(proxy),view))throw new Error("Input proxy is outside the owned music scroll view");
    var proxyView=mvReadField(proxy,"ScrollSelectView");
    if(!exists(proxyView)||String(instanceId(proxyView))!==String(instanceId(view)))throw new Error("Input proxy reverse ScrollSelectView ownership differs");
    var ownership={viewId:String(instanceId(view)),modelId:String(instanceId(model)),inputProxyId:String(instanceId(proxy)),
      inputProxyGameObjectId:String(instanceId(gameObject(proxy))),transitionId:String(instanceId(transition)),inputProxyViewId:String(instanceId(proxyView))};
    var proof={ownership:ownership,view:nativeMusicObject(view),model:nativeMusicObject(model),inputProxy:nativeMusicObject(proxy),transition:nativeMusicObject(transition),
      viewport:current.geometry.visibleBounds,modelState:{selectedCellIndex:mvNumber(mvBacking(model,"SelectedCellIndex")),
        moveToCellIndex:mvNumber(mvBacking(model,"MoveToCellIndex")),scrollPosition:nativeMusicStateVector(model,"<ScrollPosition>k__BackingField"),
        selectedCellPositionDelta:nativeMusicStateVector(model,"selectedCellPositionDelta"),cachedScrollSelectCell:nativeMusicObject(mvReadField(model,"cachedScrollSelectCell"))},
      storedProxyState:{scope:"STORED_STATE_NOT_CURRENT_INPUT_EVENT",pressPosition:null,movedOutOfTolerance:mvReadField(proxy,"movedOutOfTolerance"),
        pressedPointerId:mvReadField(proxy,"PressedPointerId"),prevPressedPointerId:mvReadField(proxy,"PrevPressedPointerId"),isDragging:mvBacking(proxy,"IsDragging")}};
    try{var press=mvReadField(proxy,"pressPosition");proof.storedProxyState.pressPosition=press?nativeMusicVector(press,["x","y","z"]):null;}catch(_){}
    var list=mvReadField(model,"managedCells");if(!exists(list))throw new Error("Native managedCells list unavailable");
    var type=fullType(list),items=mvReadField(list,"_items"),size=mvNumber(mvReadField(list,"_size"));
    if(!/^System\.Collections\.Generic\.List(?:`|<)/.test(type)||!items||typeof items.length!=="number")throw new Error("Native managedCells runtime list layout unproved");
    var seen={},cellRefs={};
    var cells=nativeMusicBoundedCells(size,items.length,function(ordinal){
      var entry=items.get(ordinal);if(!exists(entry))throw new Error("Null native list entry");
      var rect=mvBacking(entry,"RectTransform"),cell=mvReadField(entry,"scrollSelectCell");
      if(!exists(rect))throw new Error("Native managed-cell RectTransform unavailable");
      if(!descendsFrom(gameObject(rect),view))throw new Error("Native cell is outside owned scroll");
      var geometry=nativeMusicRect(rect),rectId=geometry.rectId;
      if(seen[rectId])throw new Error("Duplicate native managed-cell RectTransform");seen[rectId]=true;
      var index=mvNumber(mvBacking(entry,"Index")),positionIndex=mvNumber(mvBacking(entry,"PositionIndex"));
      if(!Number.isInteger(index)||!Number.isInteger(positionIndex))throw new Error("Native cell index is unavailable");
      var go=gameObject(rect),activeSelf=call(go,"get_activeSelf"),activeInHierarchy=call(go,"get_activeInHierarchy");
      if(typeof activeSelf!=="boolean"||typeof activeInHierarchy!=="boolean")throw new Error("Native cell active state unavailable");
      var vo=exists(cell)?mvBacking(cell,"CellVO"):null,liveId=mvNumber(mvBacking(vo,"LiveMasterId"));
      var cellId=exists(cell)?String(instanceId(cell)):null;
      if(activeInHierarchy && (!exists(cell)||!Number.isInteger(liveId)))throw new Error("Active native cell VO binding unavailable");
      if(exists(cell) && !descendsFrom(gameObject(cell),view))throw new Error("Referenced native cell VO is outside the owned scroll view");
      var value={ordinal:ordinal,index:index,positionIndex:positionIndex,rectId:rectId,cellId:cellId,liveMasterId:liveId,
        rectGameObjectId:String(instanceId(go)),cellGameObjectId:exists(cell)?String(instanceId(gameObject(cell))):null,
        bindingSource:"Exact managed entry RectTransform and scrollSelectCell references; no same-GameObject assumption",
        isPlayable:mvBacking(vo,"IsPlayable"),activeSelf:activeSelf,activeInHierarchy:activeInHierarchy,
        path:geometry.path,nativeBounds:geometry.nativeBounds,geometry:geometry,voClass:vo?fullType(vo):null};
      if(exists(cell))cellRefs[cellId]={cell:cell,rect:rect};return value;
    });
    cells.runtimeType=type;proof.managedCells=cells;result.proof.owners.push(proof);
    if(!cells.complete)throw new Error(cells.reason);
    result.owners.push({view:view,model:model,proxy:proxy,transition:transition,geometry:current.geometry,proof:proof,cellRefs:cellRefs});
    result.proof.complete=true;
  }catch(error){result.proof.reason=String(error);}
  return result;
}
function nativeMusicRaycast(screen,point,raycaster,owner) {
  if(typeof raycaster.inspect!=="function")return {qualified:false,reason:"Current native raycast inspection unavailable",proof:{available:false}};
  var query=raycaster.inspect(point),proof=query.proof;
  if(!proof.available || !query.hit || !query.module)return {qualified:false,reason:"Current first graphic/raycaster unavailable",proof:proof};
  var camera=nativeMusicEventCamera(query.module);proof.eventCamera=camera.proof;
  if(!camera.proof.resolved)return {qualified:false,reason:"Current event camera could not be resolved",proof:proof};
  var execute=findClass("UnityEngine.EventSystems.ExecuteEvents",true),handler=findClass("UnityEngine.EventSystems.IDragHandler",true);
  if(!execute||!handler)return {qualified:false,reason:"Current Unity drag-handler metadata unavailable",proof:proof};
  var drag=execute.method("GetEventHandler",1).inflate(handler).invoke(query.hit);
  if(!exists(drag)||String(instanceId(drag))!==String(instanceId(gameObject(owner.proxy))))return {qualified:false,reason:"Current first graphic drag owner is not the owned inputProxy",proof:proof};
  var rect=component(drag,runtime.rectTransform);if(!exists(rect))return {qualified:false,reason:"Owned drag-handler RectTransform plane unavailable",proof:proof};
  proof.dragOwner=nativeMusicObject(drag);proof.dragRect=nativeMusicRect(rect);
  return {qualified:true,proof:proof,camera:camera.camera,cameraProof:camera.proof,drag:drag,rect:rect,module:query.module};
}
function nativeMusicWorldPoint(rect,camera,point,screen) {
  var storage=Memory.alloc(runtime.vector3.valueTypeSize),value=new Il2Cpp.ValueType(storage,runtime.vector3.type);
  ["x","y","z"].forEach(function(axis){value.field(axis).value=0;});
  var unityPoint=vector(runtime.vector2,point.x,screen.height-point.y);
  var converted=runtime.rectUtility.method("ScreenPointToWorldPointInRectangle",4).invoke(rect,unityPoint,camera,new Il2Cpp.Reference(storage,runtime.vector3.type));
  return {converted:converted===true,point:nativeMusicVector(value,["x","y","z"]),unityScreenPoint:{x:point.x,y:screen.height-point.y},scope:"OBSERVER_OWNED_OUT_STORAGE"};
}
function nativeMusicHit(screen,state,contexts,row,raycaster) {
  var result={qualified:false,reason:null,scope:"PROSPECTIVE_NATIVE_HIT_PREDICTION",intendedLiveMasterId:row.liveMasterId,cellsComplete:false,
    ownership:null,intended:null,firstContaining:null,worldPoint:null,screenPoint:null,orderedCells:[],listSignature:null};
  try {
    if(!state.nativeMusicSelection.complete||contexts.owners.length!==1)throw new Error(state.nativeMusicSelection.reason||"Native music ownership incomplete");
    var owner=contexts.owners[0],entries=owner.proof.managedCells.entries;
    result.nativeStateBefore={scope:"READ_ONLY_STORED_STATE_NOT_CURRENT_INPUT_EVENT",frame:screen.frame,
      modelState:owner.proof.modelState,storedProxyState:owner.proof.storedProxyState,
      transition:owner.proof.transition,controllerSelection:state.musicSelection};
    result.cellsComplete=owner.proof.managedCells.complete;result.orderedCells=entries;
    result.listSignature=JSON.stringify(entries.map(function(entry){return {identity:nativeMusicCellIdentity(entry),nativeBounds:entry.nativeBounds};}));
    var intended=entries.filter(function(entry){return entry.cellId===row.id && entry.liveMasterId===row.liveMasterId;});
    if(intended.length!==1)throw new Error("Intended typed row has no unique native managed-cell binding");
    intended=intended[0];result.intended=nativeMusicCellIdentity(intended);
    if(intended.activeInHierarchy!==true||intended.isPlayable!==true)throw new Error("Intended native cell is inactive or its VO is not playable");
    var viewport=owner.geometry.visibleBounds;
    function inside(point){return Number.isInteger(point.x)&&Number.isInteger(point.y)&&point.x>=Math.max(0,viewport.left)&&point.x<Math.min(screen.width,viewport.right)&&point.y>=Math.max(0,viewport.top)&&point.y<Math.min(screen.height,viewport.bottom);}
    var centers=[row.target&&row.target.center,{x:(viewport.left+viewport.right)/2,y:(viewport.top+viewport.bottom)/2}],resolved=null;
    result.seedRaycasts=[];
    for(var i=0;i<centers.length;i++)if(centers[i]) {
      var seed={x:Math.round(centers[i].x),y:Math.round(centers[i].y)};if(!inside(seed))continue;
      var candidate=nativeMusicRaycast(screen,seed,raycaster,owner);result.seedRaycasts.push({screenPoint:seed,qualified:candidate.qualified,reason:candidate.reason||null,proof:candidate.proof});
      if(candidate.qualified){resolved=candidate;break;}
    }
    if(!resolved)throw new Error("No current owned inputProxy event-camera/drag-plane witness");
    var inputGeometry=nativeMusicViewport(owner.view,screen,resolved.camera);viewport=inputGeometry.visibleBounds;
    if(!inputGeometry.visible||!inputGeometry.groupsInteractable||!inputGeometry.blocksRaycasts)throw new Error("Current native input viewport is not actionable");
    result.viewport=viewport;
    var bounds=intended.nativeBounds;
    if(!(bounds.min.x<bounds.max.x && bounds.min.y<bounds.max.y && bounds.min.z===bounds.max.z))throw new Error("Intended signed native bounds are empty or inverted");
    var world=Memory.alloc(runtime.vector3.valueTypeSize),center=new Il2Cpp.ValueType(world,runtime.vector3.type);
    ["x","y","z"].forEach(function(axis){center.field(axis).value=Math.fround(Math.fround(bounds.min[axis]+bounds.max[axis])*.5);});
    var projected=runtime.rectUtility.method("WorldToScreenPoint",2).invoke(resolved.camera,center);
    var point={x:Math.round(field(projected,"x")),y:Math.round(screen.height-field(projected,"y"))};result.screenPoint=point;
    if(!inside(point))throw new Error("Derived integer native point is outside the current visible viewport");
    var final=nativeMusicRaycast(screen,point,raycaster,owner);result.firstGraphic=final.proof;
    if(!final.qualified)throw new Error(final.reason);
    if(JSON.stringify(final.cameraProof)!==JSON.stringify(resolved.cameraProof)||String(instanceId(final.rect))!==String(instanceId(resolved.rect))||String(instanceId(final.module))!==String(instanceId(resolved.module)))throw new Error("Derived point changed current raycaster/event-camera/drag-plane ownership");
    result.ownership=Object.assign({},owner.proof.ownership,{dragOwnerId:String(instanceId(final.drag)),dragRectId:String(instanceId(final.rect)),
      raycasterId:String(instanceId(final.module)),eventCamera:final.cameraProof});
    result.dragPlane=final.proof.dragRect;
    var converted=nativeMusicWorldPoint(final.rect,final.camera,point,screen);result.conversion=converted;result.worldPoint=converted.point;
    if(!converted.converted)throw new Error("Pure Unity point conversion returned false; zero/fallback is diagnostic only");
    var scan=nativeMusicScan(entries,intended,converted.point);result.firstContaining=scan.firstContaining;
    if(!scan.qualified)throw new Error(scan.reason);
    if(converted.point.x===bounds.min.x||converted.point.x===bounds.max.x||converted.point.y===bounds.min.y||converted.point.y===bounds.max.y)throw new Error("Derived point is on a precision-sensitive native XY boundary");
    var activity=active(owner.proxy),target={id:String(instanceId(owner.proxy)),name:text(maybe(owner.proxy,"get_name",null)),path:hierarchy(transform(owner.proxy)),
      active:activity.active,enabled:activity.enabled,visible:activity.active&&activity.enabled&&inputGeometry.visible,
      bounds:viewport,visibleBounds:viewport,center:point,groupsInteractable:inputGeometry.groupsInteractable,blocksRaycasts:inputGeometry.blocksRaycasts};
    if(!target.active||!target.enabled||!target.visible)throw new Error("Current owned inputProxy is unavailable");
    target.hit={available:true,hittable:true,hits:final.proof.hits,firstName:final.proof.firstName,firstPath:final.proof.firstPath};
    result.qualified=true;result.reason=scan.reason;return {proof:result,target:target};
  }catch(error){result.reason=String(error);return {proof:result,target:row.target};}
}

/* QA-ONLY, field-only complete suit catalog observation. Never executes an
 * input, setter, C# collection/property getter, callback or enumerator.
 * Uses existing main-thread findClass/allOfType/exists/active/mvReadField/
 * mvBacking/mvNumber/fullType/instanceId helpers and bridge native array APIs.
 * Exact original GL metadata provenance is in suit-catalog-proposal.json.
 * Missing/unsupported data stays incomplete; visible cells are no fallback.
 */
function observeExistingSuitCatalogs() {
  var MAX_ENTRIES = 4096, MAX_POPUPS = 256;
  var MEMBER_SUIT = "LLAS.DM.ValueObject.MemberSuitVO";
  var result = {complete:false,suitCatalogs:[],errors:[],
    scope:"Complete current SuitChangePopup input array + bound displayed IList; raw multiplicity/order preserved, not visible-cell counts"};
  function fail(code) { throw new Error(code); }
  function pointer(value) { return exists(value) && value.handle ? value.handle.toString() : null; }
  function asObject(value) {
    if (!exists(value)) fail("CATALOG_REFERENCE_NULL");
    return value instanceof Il2Cpp.Array ? value.object : value;
  }
  function className(klass) { return klass.namespace ? klass.namespace+"."+klass.name : klass.name; }
  function positive(value) { return Number.isInteger(value) && value>0; }
  function boundedArray(value,label,capacityLimit) {
    var object=asObject(value),klass=object.class;
    // Check the managed object's actual array rank/element metadata BEFORE
    // wrapping it as an array or reading native array length.
    var element=klass.rank===1 ? klass.elementClass : null;
    if (klass.rank!==1 || !exists(element) || className(element)!==MEMBER_SUIT)
      fail(label+"_NOT_MEMBER_SUIT_ARRAY");
    var array=value instanceof Il2Cpp.Array ? value : new Il2Cpp.Array(value.handle);
    var count=Number(array.length);
    if (!Number.isInteger(count) || count<0 || count>capacityLimit) fail(label+"_ARRAY_LENGTH_OUT_OF_QA_BOUND");
    return {array:array,count:count,pointer:pointer(value),className:className(klass)};
  }
  function readRows(array,count,label) {
    var rows=[];
    for (var i=0;i<count;i++) {
      var vo=array.get(i);
      if (!exists(vo) || fullType(vo)!==MEMBER_SUIT) fail(label+"_INVALID_MEMBER_SUIT_VO_AT_"+i);
      var id=mvNumber(mvBacking(vo,"MasterId")),member=mvNumber(mvBacking(vo,"MemberMasterId"));
      if (!positive(id) || !positive(member)) fail(label+"_INVALID_IDENTITY_AT_"+i);
      // No set/dedup operation: one output row for EVERY array/list element.
      rows.push({index:i,suitId:id,memberId:member,voPointer:pointer(vo)});
    }
    return rows;
  }
  function sameRows(first,second) {
    if (first.length!==second.length) return false;
    for (var i=0;i<first.length;i++)
      if (first[i].suitId!==second[i].suitId || first[i].memberId!==second[i].memberId) return false;
    return true;
  }
  function observe(popup) {
    var record={complete:false,id:String(instanceId(popup)),path:hierarchy(transform(popup)),active:true,popupPointer:pointer(popup),
      source:"SuitChangePopup.PopupOrder.MemberSuitVOs + referenced suit view DeliveryObject"};
    try {
      var order=mvBacking(popup,"PopupOrder"),view=mvReadField(popup,"suitChangePopupSuitTileView");
      if (!exists(order) || !exists(view)) fail("POPUP_ORDER_OR_REFERENCED_VIEW_NULL");
      var declaring=order.class.declaringClass;
      if (order.class.name!=="Order" || !declaring || className(declaring)!=="LLAS.SuitChangePopup")
        fail("POPUP_ORDER_DECLARING_CLASS_MISMATCH");
      if (fullType(view)!=="LLAS.Scene.EntryPoint.SuitChangePopupSuitTileView" || !active(view).active)
        fail("REFERENCED_SUIT_VIEW_NOT_ACTIVE_OR_WRONG_CLASS");
      var selected=mvBacking(order,"MemberSuitVO");
      if (!exists(selected) || fullType(selected)!==MEMBER_SUIT) fail("SELECTED_MEMBER_SUIT_VO_INVALID");
      var selectedMember=mvNumber(mvBacking(selected,"MemberMasterId"));
      var selectedSuit=mvNumber(mvBacking(selected,"MasterId"));
      if (!positive(selectedMember) || !positive(selectedSuit)) fail("SELECTED_MEMBER_SUIT_IDENTITY_INVALID");
      var sourceValue=mvBacking(order,"MemberSuitVOs"),source=boundedArray(sourceValue,"ORDER",MAX_ENTRIES);
      if (source.count===0) fail("ORDER_CATALOG_EMPTY");
      var rows=readRows(source.array,source.count,"ORDER"),hasSelected=false;
      for (var i=0;i<rows.length;i++) {
        if (rows[i].memberId!==selectedMember) fail("ORDER_CONTAINS_ANOTHER_CHARACTER");
        if (rows[i].suitId===selectedSuit) hasSelected=true;
      }
      var deliveryValue=mvBacking(view,"DeliveryObject");
      if (!exists(deliveryValue) || pointer(deliveryValue)!==source.pointer)
        fail("DISPLAYED_DELIVERY_IS_NOT_EXACT_ORDER_ARRAY");
      var delivery=boundedArray(deliveryValue,"DELIVERY",MAX_ENTRIES);
      if (delivery.count!==source.count) fail("DISPLAYED_DELIVERY_LENGTH_DIFFERS_FROM_ORDER");
      var again=boundedArray(mvBacking(order,"MemberSuitVOs"),"ORDER_RECHECK",MAX_ENTRIES);
      if (again.pointer!==source.pointer || again.count!==source.count ||
          !sameRows(readRows(again.array,again.count,"ORDER_RECHECK"),rows) ||
          pointer(mvBacking(popup,"PopupOrder"))!==pointer(order) ||
          pointer(mvReadField(popup,"suitChangePopupSuitTileView"))!==pointer(view) ||
          pointer(mvBacking(view,"DeliveryObject"))!==pointer(deliveryValue))
        fail("CATALOG_BINDING_CHANGED_DURING_READ");
      record.complete=true;
      record.memberId=selectedMember;record.selectedSuitId=selectedSuit;
      record.orderPointer=pointer(order);record.viewId=String(instanceId(view));record.viewPointer=pointer(view);
      record.orderArrayPointer=source.pointer;record.arrayLength=source.count;
      record.rows=rows.map(function(row){return {memberId:row.memberId,suitId:row.suitId};});
      record.voPointers=rows.map(function(row){return row.voPointer;});
      record.selectedSuitPresentInCatalog=hasSelected;
      record.delivery={kind:"MemberSuitVO[]",pointer:delivery.pointer,count:delivery.count,sameArrayReference:true};
      record.completeness="Every Order.MemberSuitVOs element read; referenced displayed DeliveryObject is the exact same array; binding/count/content stable within callback";
    } catch (error) {record.error=String(error);}
    return record;
  }
  try {
    var klass=findClass("LLAS.SuitChangePopup",true);
    if (!klass) {result.errors.push("SUIT_CHANGE_POPUP_TYPE_ABSENT");return result;}
    var objects=allOfType(klass);
    if (objects.length>MAX_POPUPS) {result.errors.push("POPUP_OBJECT_COUNT_EXCEEDS_QA_BOUND");return result;}
    for (var i=0;i<objects.length;i++) {
      var object=objects.get(i);
      if (exists(object) && active(object).active) result.suitCatalogs.push(observe(object));
    }
    result.complete=result.suitCatalogs.length===1 && result.suitCatalogs[0].complete===true;
    if (result.suitCatalogs.length>1) {
      result.errors.push("MULTIPLE_ACTIVE_SUIT_CHANGE_POPUPS");
      // Flattening the records into the parent snapshot must not lose the
      // global ambiguity gate, even if only one popup matches a member ID.
      result.suitCatalogs.forEach(function(record){
        record.complete=false;record.error=record.error || "MULTIPLE_ACTIVE_SUIT_CHANGE_POPUPS";
      });
    }
  } catch (error) {result.errors.push(String(error));}
  return result;
}

function observeExistingMvState(screen,nativeContext) {
  screen = screen || metadata();
  var raycaster = makeRaycaster(screen);
  var result = { deckCells: [], pickerCells: [], liveMembers: [], errors: [] };
  var specifications = [
    ["LLAS.Components.UI.LiveMvDeckMemberParts", function (object) {
      var vo = mvReadField(object,"deckMemberVO"), suit = mvBacking(vo,"MemberSuitVO");
      var info = mvExistingComponentInfo(object);
      info.memberId = mvNumber(mvBacking(vo,"MemberMasterId"));
      info.formationPosition = mvNumber(mvBacking(vo,"Position"));
      info.suitId = mvNumber(mvBacking(suit,"MasterId"));
      info.voClass = vo ? fullType(vo) : null;
      // Button references identify the actual visible targets. Existing
      // snapshot projection can compute their current RectTransform bounds.
      ["memberButton","suitButton"].forEach(function (key) {
        var button = mvReadField(object,key);
        if (exists(button)) info[key] = mvUiTarget(button,screen,raycaster);
      });
      result.deckCells.push(info);
    }],
    ["LLAS.Scene.LiveMvDeckSelect.LiveMvDeckMemberSelectCategorizedListViewCell", function (object) {
      var vo = mvBacking(object,"liveMvMemberVO"), info = mvExistingComponentInfo(object);
      var thumbnail = mvBacking(vo,"MemberThumbnailVO");
      info.memberId = mvNumber(mvBacking(vo,"MemberMasterId"));
      if (info.memberId === null) info.memberId = mvNumber(mvBacking(thumbnail,"MemberMasterId"));
      try { info.target = mvUiTarget(object,screen,raycaster); } catch (_) {}
      // If a regional VO computes this getter rather than storing it, record
      // null and the real class; do not invent an ID or call a selection action.
      info.voClass = vo ? fullType(vo) : null;
      result.pickerCells.push(info);
    }],
    ["LLAS.Scene.Live.Components.LiveCoreMember", function (object) {
      var memberInfo = mvReadField(object,"memberInfo"), info = mvExistingComponentInfo(object);
      info.formationPosition = mvNumber(mvBacking(memberInfo,"FormationPosition"));
      result.liveMembers.push(info);
    }]
  ];
  specifications.forEach(function (specification) {
    var klass = findClass(specification[0],true);
    if (!klass) { result.errors.push({type:specification[0],error:"Type absent"}); return; }
    try {
      var objects = allOfType(klass);
      for (var i=0;i<objects.length && i<128;i++) {
        var object = objects.get(i);
        if (exists(object) && active(object).active) specification[1](object);
      }
    } catch(error) { result.errors.push({type:specification[0],error:String(error)}); }
  });
  var catalogs=observeExistingSuitCatalogs();result.suitCatalogs=catalogs.suitCatalogs;result.suitCatalogErrors=catalogs.errors;
  var extras=observeExistingMvExtras(screen,raycaster);
  result.deckRoots=extras.deckRoots;result.suitPickerCells=extras.suitPickerCells;result.directorAssets=extras.directorAssets;
  result.errors=result.errors.concat(extras.errors);
  result.standingMemberNum=extras.deckRoots.length===1?extras.deckRoots[0].standingMemberNum:null;
  result.liveMasterId=extras.deckRoots.length===1?extras.deckRoots[0].liveMasterId:null;
  var music=observeExistingMusicRowsAndMvTabs(screen,raycaster);result.musicRows=music.musicRows;result.musicSelection=music.musicSelection;result.deckTabGroups=music.deckTabGroups;result.errors=result.errors.concat(music.errors);
  var nativeMusic=observeNativeMusicSelection(screen,result.musicRows);result.nativeMusicSelection=nativeMusic.proof;
  if(nativeContext)nativeContext.owners=nativeMusic.owners;
  result.liveMembers.forEach(function(member){
    var found=[];
    extras.directorAssets.forEach(function(director){director.members.forEach(function(asset){
      if(asset.formationPosition===member.formationPosition && asset.memberId!==null && asset.suitId!==null) found.push({asset:asset,path:director.path});
    });});
    if(found.length===1){member.memberId=found[0].asset.memberId;member.suitId=found[0].asset.suitId;member.assetIdentitySource=found[0].path;}
  });
  return result;
}

function mvUiTarget(object,screen,raycaster) {
  var geometry = rectAndClipping(transform(object),screen), activity = active(object);
  var target = {id:String(instanceId(object)),name:text(maybe(object,"get_name",null)),path:hierarchy(transform(object)),
    active:activity.active,enabled:activity.enabled,visible:activity.active && activity.enabled && geometry.visible,
    bounds:geometry.bounds,visibleBounds:geometry.visibleBounds,center:geometry.center,
    groupsInteractable:geometry.groupsInteractable,blocksRaycasts:geometry.blocksRaycasts};
  if (target.visible && raycaster.available) target.hit = raycaster.test(target.center,object);
  return target;
}
function pickExistingMvTarget(query) {
  query = query || {}; var screen = metadata(),nativeContext={owners:[]},state = observeExistingMvState(screen,nativeContext), matches = [];
  if (query.role === "member" || query.role === "suit") {
    state.deckCells.forEach(function(cell) {
      if (cell.formationPosition === Number(query.formationPosition) && /DeckMemberCustomVO$/.test(cell.voClass || "")) {
        var target = cell[query.role + "Button"]; if (target) matches.push({target:target,cell:cell});
      }
    });
  } else if (query.role === "picker") {
    state.pickerCells.forEach(function(cell) {
      if (cell.memberId === Number(query.memberId) && cell.target) matches.push({target:cell.target,cell:cell});
    });
  } else if(query.role === "suitPicker") {
    state.suitPickerCells.forEach(function(cell){
      if(cell.suitId===Number(query.suitId) && (query.memberId===undefined || cell.memberId===Number(query.memberId)) && cell.target) matches.push({target:cell.target,cell:cell});
    });
  } else if(query.role === "music") {
    state.musicRows.forEach(function(cell){if(cell.liveMasterId===Number(query.liveMasterId) && cell.isPlayable===true && cell.target) matches.push({target:cell.target,cell:cell});});
  } else if(query.role === "customTab") {
    state.deckTabGroups.forEach(function(group){group.tabs.forEach(function(tab){if(tab.deckType===2 && tab.target)matches.push({target:tab.target,cell:tab});});});
  } else throw new Error("Unknown read-only MV picker role");
  if(query.role!=="music")matches = matches.filter(function(entry) {var t=entry.target;return t.active && t.enabled && t.visible && t.groupsInteractable && t.blocksRaycasts && t.hit && t.hit.available && t.hit.hittable;});
  if (matches.length !== 1) throw new Error(JSON.stringify({error:"MV target absent, obscured or ambiguous",query:query,matches:matches.length,state:state,screen:screen}));
  var musicHit=query.role==="music"?nativeMusicHit(screen,state,nativeContext,matches[0].cell,makeRaycaster(screen)):null;
  var target=musicHit?musicHit.target:matches[0].target;
  return {timestampMs:Date.now(),screen:screen,target:target,catalog:matches[0].cell,nativeMusicHit:musicHit?musicHit.proof:null,
    input:{method:"adb shell input tap",x:target.center.x,y:target.center.y},
    coordinateSource:"Existing MV model identity and live RectTransform/raycast geometry; no selection method invoked"};
}

// Read-only fields verified in GL/JP metadata: Jigbox.Tween.TweenColor -> TweenBase<Color>
// -> PeriodicMovement<...>, not DG.Tweening.Tween. No callbacks/setters invoked.
function jigboxTweenFields(tween) {
  var behaviour=mvReadField(tween,"behaviour");
  return {id:tween.handle.toString(),type:fullType(tween),duration:numericField(tween,"duration"),
    progressTime:behaviour?numericField(behaviour,"progressTime"):null,
    deltaTime:behaviour?numericField(behaviour,"<DeltaTime>k__BackingField"):null,
    lastCompleteCount:behaviour?numericField(behaviour,"<LastCompleteCount>k__BackingField"):null,
    loopCount:behaviour?numericField(behaviour,"<LoopCount>k__BackingField"):null};
}
function splashFadeRGBA(splash) {
  var image=mvReadField(splash,"fade"),color=maybe(image,"get_color",null);
  if(!color)return null;
  return {r:numericField(color,"r"),g:numericField(color,"g"),b:numericField(color,"b"),a:numericField(color,"a")};
}

  function observeDownloadSettings(screen) {
    var result=[],raycaster=makeRaycaster(screen);
    // The first-login dialog and the normal settings dialog have distinct
    // observed MonoBehaviour types with the same serialized caption/toggle fields.
    ["LLAS.ModeSelectableDownloadConfirmPopup","LLAS.DownloadSettingPopup"].forEach(function(typeName){
      var klass=findClass(typeName,true);if(!klass)return;
      var objects=allOfType(klass);
      for(var i=0;i<objects.length && i<12;i++) {
        var popup=objects.get(i);if(!active(popup).active)continue;
        var info={id:String(instanceId(popup)),type:typeName,path:hierarchy(transform(popup)),options:[],toggles:[],downloadType:numericField(popup,"downloadType")};
        ["fullDownloadItemText","lightnessDownloadItemText","autoDeleteDownloadItemText"].forEach(function(name){
          var caption=mvReadField(popup,name),view=mvReadField(caption,"textView");
          if(exists(view))info.options.push({role:name,referencePath:hierarchy(transform(caption)),
            path:hierarchy(transform(view)),text:componentText(view)});
        });
        var group=mvReadField(popup,"productToggleGroup"),list=mvReadField(group,"toggles"),items=mvReadField(list,"_items"),size=mvNumber(mvReadField(list,"_size"));
        if(items&&typeof items.length==="number"&&size!==null)for(var j=0;j<size&&j<items.length&&j<8;j++) {
          var toggle=items.get(j),button=mvReadField(toggle,"button");
          var entry={path:hierarchy(transform(toggle)),isOn:mvReadField(toggle,"isOn"),label:exists(button)?descendantText(button):""};
          if(exists(button))entry.target=mvUiTarget(button,screen,raycaster);
          info.toggles.push(entry);
        }
        result.push(info);
      }
    });
    return result;
  }
  function featureState() {
    var result = { native: nativeFeatureState(), aspectCorrectors: [], splashScreens: [], mv:observeExistingMvState(), downloadSettings:cachedMainRequested?observeDownloadSettings(metadata()):[], diagnostics: [] };
    var aspect = findClass("LLAS.Scene.Live.Components.CameraAspectCorrector", true);
    if (aspect) try {
      var objects = allOfType(aspect);
      for (var i = 0; i < objects.length && i < 128; i++) {
        var object = objects.get(i), state = active(object);
        if (!state.active) continue;
        var item = { id: String(instanceId(object)), path: hierarchy(transform(object)), active: state.active,
          enabled:maybe(object,"get_enabled",null)===true,
          mode: numericField(object, "mode"), correction: numericField(object, "<Correction>k__BackingField"),
          defaultOrthographicSize: numericField(object, "defaultOrthographicSize") };
        try {
          var camera = object.field("target").value;
          item.camera = { id:String(instanceId(camera)),fieldOfView: Number(maybe(camera, "get_fieldOfView", NaN)),
            orthographicSize: Number(maybe(camera, "get_orthographicSize", NaN)),
            orthographic: !!maybe(camera, "get_orthographic", false),
            active:maybe(gameObject(camera),"get_activeInHierarchy",false)===true,
            enabled:maybe(camera,"get_enabled",null)===true,
            pixelWidth:Number(maybe(camera,"get_pixelWidth",NaN)),pixelHeight:Number(maybe(camera,"get_pixelHeight",NaN)) };
          var texture=maybe(camera,"get_targetTexture",undefined);
          item.camera.targetTextureKnown=texture!==undefined;
          item.camera.onScreenDefaultTarget=texture!==undefined && !exists(texture);
          item.camera.targetTexturePointer=exists(texture)?texture.handle.toString():null;
        } catch (_) {}
        result.aspectCorrectors.push(item);
      }
    } catch (error) { result.diagnostics.push({type:"aspect", error:String(error)}); }
    var splash = findClass("LLAS.Scene.Title.SplashScreen", true);
    if (splash) try {
      var screens = allOfType(splash);
      for (var j = 0; j < screens.length && j < 24; j++) {
        var screen = screens.get(j), state2 = active(screen);
        if (!state2.active) continue;
        var sample = { id: String(instanceId(screen)), path: hierarchy(transform(screen)), active: true,
          fadeDuration: numericField(screen,"fadeDuration"), splashDuration:numericField(screen,"splashDuration"),
          intervalDuration:numericField(screen,"intervalDuration"), skipDuration:numericField(screen,"skipDuration") };
        try {
          var tween = screen.field("fadeTween").value;
          if (exists(tween)) sample.tween = jigboxTweenFields(tween);
        } catch (_) {}
        sample.fadeRGBA=splashFadeRGBA(screen);
        result.splashScreens.push(sample);
      }
    } catch (error) { result.diagnostics.push({type:"splash", error:String(error)}); }
    return result;
  }
  var introTrace = { samples: [], startedMs: null, lastError: null }, introTimer = null, introPending = false;
  function beginIntroTrace() {
    if (introTimer) clearInterval(introTimer);
    introTrace = { samples: [], startedMs:Date.now(), lastError:null };
    introTimer = setInterval(function () {
      if (introPending || introTrace.samples.length >= 3000 || Date.now()-introTrace.startedMs > 180000) return;
      introPending = true;
      onMain(function () {
        var klass=findClass("LLAS.Scene.Title.SplashScreen",true), items=[];
        if (klass) {
          var objects=allOfType(klass);
          for(var i=0;i<objects.length && i<24;i++) {
            var object=objects.get(i); if(!active(object).active) continue;
            var item={id:String(instanceId(object)),fadeDuration:numericField(object,"fadeDuration"),splashDuration:numericField(object,"splashDuration")};
            var tween=mvReadField(object,"fadeTween");
            if(exists(tween)) item.tween=jigboxTweenFields(tween);
            item.fadeRGBA=splashFadeRGBA(object);
            items.push(item);
          }
        }
        var sample={timestampMs:Date.now(),screen:metadata(),config:nativeFeatureState().config,splashScreens:items};
        if(items.length || introTrace.samples.length<3 || (introTrace.samples.length && introTrace.samples[introTrace.samples.length-1].splashScreens.length)) introTrace.samples.push(sample);
      }).catch(function(error){introTrace.lastError=String(error);}).finally(function(){introPending=false;});
    },25);
    return {startedMs:introTrace.startedMs,intervalMs:25,scope:"Read-only main-thread splash/tween fields; no callbacks or setters"};
  }
  function endIntroTrace() { if(introTimer)clearInterval(introTimer);introTimer=null;return Object.assign({},introTrace,{pendingManagedWork:introPending||initPending}); }
  function discoverActiveCustomButtons() {
    if (!runtime.rectTransform || !runtime.component) return [];
    var names = [], seen = {}, rects = allOfType(runtime.rectTransform), inspected = 0;
    for (var i = 0; i < rects.length && inspected < 600 && names.length < 24; i++) {
      var rect = rects.get(i); if (!active(rect).active) continue; inspected++;
      try {
        var components = overloaded(gameObject(rect), "GetComponents", ["System.Type"], [runtime.component.type.object]);
        for (var j = 0; j < components.length && names.length < 24; j++) {
          var object = components.get(j); if (!exists(object)) continue;
          var name = fullType(object);
          if (/button|click|touchable|eventtrigger/i.test(name) && !seen[name] && DEFAULT_TYPES.indexOf(name) < 0) { seen[name] = true; names.push(name); }
        }
      } catch (_) {}
    }
    return names;
  }
  function descendsFrom(object, target) {
    var tr = transform(object), goal = gameObject(target).handle, count = 0;
    while (exists(tr) && count++ < 64) {
      if (gameObject(tr).handle.equals(goal)) return true;
      tr = maybe(tr, "get_parent", null);
    }
    return false;
  }
  function makeRaycaster(screen) {
    try {
      if (!runtime.eventSystem || !runtime.pointerData || !runtime.raycastResult) throw new Error("Unity EventSystem metadata is unavailable");
      var system = call(runtime.eventSystem, "get_current");
      if (!exists(system)) throw new Error("No current Unity EventSystem");
      var data = runtime.pointerData.alloc(); call(data, ".ctor", [system]);
      var listClass = Il2Cpp.corlib.class("System.Collections.Generic.List`1").inflate(runtime.raycastResult);
      var results = listClass.alloc(); call(results, ".ctor");
      return { available: true, test: function (point, target) {
        call(data, "set_position", [vector(runtime.vector2, point.x, screen.height - point.y)]);
        call(system, "RaycastAll", [data, results]);
        var count = Number(call(results, "get_Count"));
        if (!count) return { available: true, hittable: false, hits: 0 };
        var first = call(results, "get_Item", [0]);
        var hit = maybe(first, "get_gameObject", null);
        if (!exists(hit)) return { available: true, hittable: false, hits: count };
        return { available: true, hittable: descendsFrom(hit, target), hits: count,
          firstName: text(maybe(hit, "get_name", null)), firstPath: hierarchy(transform(hit)) };
      }, inspect: function (point) {
        call(data,"set_position",[vector(runtime.vector2,point.x,screen.height-point.y)]);
        call(system,"RaycastAll",[data,results]);
        var count=Number(call(results,"get_Count")),proof={available:true,hits:count,screenPoint:{x:point.x,y:point.y},
          unityScreenPoint:{x:point.x,y:screen.height-point.y},scope:"SYNTHETIC_READ_ONLY_RAYCAST_QUERY_NOT_ACTUAL_INPUT"};
        if(!count)return {proof:proof,hit:null,module:null};
        var first=call(results,"get_Item",[0]),hit=maybe(first,"get_gameObject",null),module=mvReadField(first,"module");
        proof.firstId=exists(hit)?String(instanceId(hit)):null;proof.firstName=exists(hit)?text(maybe(hit,"get_name",null)):null;
        proof.firstPath=exists(hit)?hierarchy(transform(hit)):null;proof.raycaster=nativeMusicObject(module);
        ["distance","depth","sortingLayer","sortingOrder","index"].forEach(function(key){proof[key]=mvNumber(mvReadField(first,key));});
        ["worldPosition","worldNormal"].forEach(function(key){try{var value=mvReadField(first,key);proof[key]=value?nativeMusicVector(value,["x","y","z"]):null;}catch(_){proof[key]=null;}});
        return {proof:proof,hit:hit,module:module};
      } };
    } catch (error) { return { available: false, error: String(error), test: function () { return { available: false, hittable: null, error: String(error) }; } }; }
  }
  function metadata() {
    var scene = null;
    try { scene = text(call(call(runtime.sceneManager, "GetActiveScene"), "get_name")); } catch (_) {}
    return { width: Number(call(runtime.screen, "get_width")), height: Number(call(runtime.screen, "get_height")),
      orientation: Number(maybe(runtime.screen, "get_orientation", -1)), scene: scene,
      frame: Number(maybe(runtime.time, "get_frameCount", -1)), unityVersion: Il2Cpp.unityVersion };
  }
  function snapshot(options) {
    options = options || {};
    var screen = metadata(), nodes = [], diagnostics = [], seen = {}, maxNodes = Math.min(3000, Math.max(1, Number(options.maxNodes) || 1000));
    var customTypes = options.customButtons === false ? [] : discoverActiveCustomButtons();
    var types = DEFAULT_TYPES.concat(customTypes, Array.isArray(options.extraTypes) ? options.extraTypes.slice(0, 12) : []);
    if (options.allSelectables) types.push("UnityEngine.UI.Selectable");
    var raycaster = options.raycast === false ? { available: false, error: "Disabled by request" } : makeRaycaster(screen);
    var started = Date.now(), enumerated = 0;
    types.forEach(function (typeName) {
      var klass = findClass(String(typeName), true); if (!klass) return;
      var objects;
      try { objects = allOfType(klass); } catch (error) { diagnostics.push({ type: typeName, error: String(error) }); return; }
      for (var i = 0; i < objects.length && nodes.length < maxNodes; i++) {
        var object = objects.get(i); enumerated++;
        try {
          if (!exists(object) || seen[object.handle.toString()]) continue;
          seen[object.handle.toString()] = true;
          var activity = active(object); if (!activity.active && !options.includeInactive) continue;
          var tr = transform(object); if (!exists(tr)) continue;
          var geometry;
          try { geometry = rectAndClipping(tr, screen); } catch (error) {
            if (diagnostics.length < 24) diagnostics.push({ type: fullType(object), name: text(maybe(object, "get_name", null)), error: String(error) });
            continue;
          }
          var selected = runtime.selectable && (object.class.handle.equals(runtime.selectable.handle) || object.class.isSubclassOf(runtime.selectable, false)) ? object : nearestSelectable(tr);
          var kind = TEXT_TYPES.indexOf(typeName) >= 0 ? "text" : /InputField/.test(typeName) ? "input" : /Toggle/.test(typeName) ? "toggle" : /ScrollRect/.test(typeName) ? "scroll" : "button";
          var inputOwner = kind === "input" ? object : kind === "text" ? nearestInput(tr) : null;
          var inputState = exists(inputOwner) ? inputDescription(inputOwner, options.numericTestId) : null;
          var ownText = redactInputText(componentText(object), inputOwner, inputState);
          if (kind === "input") ownText = inputState.value || (inputState.redacted ? "[redacted input]" : "");
          var record = { id: String(instanceId(object)), type: fullType(object), kind: kind,
            name: text(maybe(object, "get_name", null)), path: hierarchy(tr), text: ownText,
            label: kind === "text" ? ownText : redactInputText(descendantText(object), inputOwner, inputState), active: activity.active, enabled: activity.enabled,
            interactable: exists(selected) ? interactable(selected) : interactable(object),
            bounds: geometry.bounds, visibleBounds: geometry.visibleBounds, center: geometry.center,
            visible: activity.active && activity.enabled && geometry.visible,
            alpha: geometry.alpha, groupsInteractable: geometry.groupsInteractable,
            blocksRaycasts: geometry.blocksRaycasts, canvas: geometry.canvas };
          if(kind === "toggle") record.toggle={isOn:maybe(object,"get_isOn",null)};
          if(kind === "scroll") {
            record.scroll={horizontal:!!maybe(object,"get_horizontal",false),vertical:!!maybe(object,"get_vertical",false)};
            var position=maybe(object,"get_normalizedPosition",null);
            if(position)record.scroll.normalizedPosition={x:field(position,"x"),y:field(position,"y")};
          }
          if (inputState) record.input = inputState;
          if (exists(selected)) record.action = { id: String(instanceId(selected)), type: fullType(selected), name: text(maybe(selected, "get_name", null)), path: hierarchy(transform(selected)) };
          if (record.visible && record.interactable !== false && geometry.groupsInteractable && geometry.blocksRaycasts && raycaster.available && (kind !== "text" || options.raycastText)) {
            try { record.hit = raycaster.test(record.center, exists(selected) ? selected : object); }
            catch (error) { record.hit = { available: false, hittable: null, error: String(error) }; }
          }
          nodes.push(record);
        } catch (error) { if (diagnostics.length < 24) diagnostics.push({ type: typeName, error: String(error) }); }
      }
    });
    return { agentVersion: AGENT_VERSION, timestampMs: Date.now(), screen: screen, nodes: nodes, features: featureState(),
      enumeratedObjects: enumerated, customButtonTypes: customTypes, truncated: nodes.length >= maxNodes, elapsedMs: Date.now() - started,
      hitTest: { available: raycaster.available, error: raycaster.error || null }, diagnostics: diagnostics };
  }
  function normalize(value) { return String(value || "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim().toLowerCase(); }
  function choose(query) {
    query = query || {};
    if (!query.id && !query.text && !query.name && !query.path && !Array.isArray(query.textAny)) throw new Error("pick needs id, text, textAny, name or path");
    var snapshotOptions = { maxNodes: query.maxNodes || 1000, extraTypes: query.extraTypes || [], allSelectables: !!query.allSelectables, raycastText: true,
      customButtons: query.customButtons !== false, numericTestId: query.numericTestId };
    var observed = snapshot(snapshotOptions);
    function matches(actual, expected) { return query.exact === false ? normalize(actual).indexOf(normalize(expected)) >= 0 : normalize(actual) === normalize(expected); }
    // Diagnose only this same returned enumeration, before actionability
    // filters. An absent candidate is not proof of destruction or inactivity.
    // A kind alone never selects unrelated nodes for these bounded summaries.
    var identityCandidates = [];
    observed.nodes.forEach(function (node) {
      var by = [];
      if (query.id && node.id === String(query.id)) by.push("id");
      if (query.path && matches(node.path, query.path)) by.push("path");
      if (query.name && matches(node.name, query.name)) by.push("name");
      if (query.text && (matches(node.text, query.text) || matches(node.label, query.text))) by.push("text");
      if (Array.isArray(query.textAny) && query.textAny.some(function (value) { return matches(node.text, value) || matches(node.label, value); })) by.push("textAny");
      if (by.length) identityCandidates.push({ node: node, matchedBy: by });
    });
    function rejectionReasons(node) {
      var reasons = [];
      if (!node.visible) reasons.push("not-visible");
      if (!node.enabled) reasons.push("not-enabled");
      if (node.interactable === false) reasons.push("not-interactable");
      if (!node.groupsInteractable) reasons.push("groups-not-interactable");
      if (!node.blocksRaycasts) reasons.push("raycasts-not-blocked");
      if (node.kind === "input" && node.input && node.input.readOnly) reasons.push("read-only-input");
      if (query.kind && node.kind !== query.kind) reasons.push("kind-mismatch");
      if (query.id && node.id !== String(query.id)) reasons.push("id-mismatch");
      if (query.name && !matches(node.name, query.name)) reasons.push("name-mismatch");
      if (query.path && !matches(node.path, query.path)) reasons.push("path-mismatch");
      if (query.text && !matches(node.text, query.text) && !matches(node.label, query.text)) reasons.push("text-mismatch");
      if (Array.isArray(query.textAny) && !query.textAny.some(function (value) { return matches(node.text, value) || matches(node.label, value); })) reasons.push("textAny-mismatch");
      if (node.hit && node.hit.hittable === false) reasons.push("raycast-rejected");
      if (query.requireHitTest && (!node.hit || !node.hit.available || !node.hit.hittable)) reasons.push("required-hit-test-failed");
      return reasons;
    }
    function boundedText(value,limit) { return value === undefined || value === null ? null : String(value).slice(0,limit); }
    function candidateSummary(entry) {
      var node=entry.node,hit=node.hit,action=node.action;
      return { id:node.id,kind:node.kind,name:boundedText(node.name,128),path:boundedText(node.path,384),
        text:boundedText(node.text,160),label:boundedText(node.label,160),matchedBy:entry.matchedBy,
        active:node.active,visible:node.visible,enabled:node.enabled,
        interactable:node.interactable === undefined ? null : node.interactable,
        groupsInteractable:node.groupsInteractable,blocksRaycasts:node.blocksRaycasts,
        inputReadOnly:node.input ? !!node.input.readOnly : null,
        hit:hit ? {available:hit.available,hittable:hit.hittable,hits:hit.hits,
          firstName:boundedText(hit.firstName,128),firstPath:boundedText(hit.firstPath,384)} : null,
        action:action ? {id:action.id,type:boundedText(action.type,160),path:boundedText(action.path,384)} : null,
        bounds:node.bounds,visibleBounds:node.visibleBounds,center:node.center,rejectedBy:rejectionReasons(node) };
    }
    var matchesFound = observed.nodes.filter(function (node) {
      if (!node.visible || !node.enabled || node.interactable === false || !node.groupsInteractable || !node.blocksRaycasts) return false;
      if (node.kind === "input" && node.input && node.input.readOnly) return false;
      if (query.kind && node.kind !== query.kind || query.id && node.id !== String(query.id)) return false;
      if (query.name && !matches(node.name, query.name) || query.path && !matches(node.path, query.path)) return false;
      if (query.text && !matches(node.text, query.text) && !matches(node.label, query.text)) return false;
      if (Array.isArray(query.textAny) && !query.textAny.some(function (value) { return matches(node.text, value) || matches(node.label, value); })) return false;
      if (node.hit && node.hit.hittable === false) return false;
      if (query.requireHitTest && (!node.hit || !node.hit.available || !node.hit.hittable)) return false;
      return true;
    });
    // A button and its caption refer to the same native action. Keep one action
    // endpoint instead of reporting an artificial ambiguity for the same tap.
    var unique = [], actionIds = {};
    matchesFound.sort(function (a, b) { return (a.kind === "text" ? 1 : 0) - (b.kind === "text" ? 1 : 0); });
    matchesFound.forEach(function (node) { var key = node.action ? "action:" + node.action.id : "object:" + node.id; if (!actionIds[key]) { unique.push(node); actionIds[key] = true; } });
    if (unique.length !== 1) throw new Error(JSON.stringify({ error: unique.length ? "Ambiguous active semantic UI targets" : "No active semantic UI target",
      errorCode:unique.length ? "SEMANTIC_TARGET_AMBIGUOUS" : "SEMANTIC_TARGET_UNAVAILABLE",query: query,
      matches: unique.slice(0, 12).map(function (node) { return { id: node.id, name: node.name, path: node.path, text: node.text, label: node.label, center: node.center }; }),
      candidateCount:identityCandidates.length,candidateLimit:16,candidatesTruncated:identityCandidates.length>16,
      candidates:identityCandidates.slice(0,16).map(candidateSummary),matchCount:matchesFound.length,uniqueMatchCount:unique.length,
      timestampMs:observed.timestampMs,snapshot:{nodeCount:observed.nodes.length,enumeratedObjects:observed.enumeratedObjects,
        truncated:observed.truncated,options:snapshotOptions,includeInactive:false,
        effectiveMaxNodes:Math.min(3000,Math.max(1,Number(snapshotOptions.maxNodes)||1000))},
      musicSelection:observed.features && observed.features.mv ? observed.features.mv.musicSelection : [],
      screen: observed.screen, hitTest: observed.hitTest, diagnostics: observed.diagnostics }));
    return { timestampMs: observed.timestampMs, screen: observed.screen, target: unique[0],
      musicSelection:observed.features && observed.features.mv ? observed.features.mv.musicSelection : [],
      input: { method: "adb shell input tap", x: unique[0].center.x, y: unique[0].center.y },
      coordinateSource: "Live Unity RectTransform world corners projected through its Canvas camera; Android top-left origin" };
  }
  function initialize() {
    runtime.screen = findClass("UnityEngine.Screen"); runtime.resources = findClass("UnityEngine.Resources");
    runtime.unityObject = findClass("UnityEngine.Object"); runtime.vector2 = findClass("UnityEngine.Vector2"); runtime.vector3 = findClass("UnityEngine.Vector3");
    runtime.rectUtility = findClass("UnityEngine.RectTransformUtility"); runtime.canvas = findClass("UnityEngine.Canvas");
    runtime.rectTransform = findClass("UnityEngine.RectTransform", true); runtime.component = findClass("UnityEngine.Component", true);
    runtime.canvasGroup = findClass("UnityEngine.CanvasGroup", true); runtime.camera = findClass("UnityEngine.Camera");
    runtime.selectable = findClass("UnityEngine.UI.Selectable", true); runtime.text = findClass("UnityEngine.UI.Text", true); runtime.tmpText = findClass("TMPro.TMP_Text", true);
    runtime.textClasses = TEXT_TYPES.map(function (name) { return findClass(name, true); }).filter(function (klass) { return !!klass; });
    runtime.inputField = findClass("UnityEngine.UI.InputField", true); runtime.tmpInputField = findClass("TMPro.TMP_InputField", true);
    runtime.rectMask = findClass("UnityEngine.UI.RectMask2D", true); runtime.mask = findClass("UnityEngine.UI.Mask", true);
    runtime.sceneManager = findClass("UnityEngine.SceneManagement.SceneManager", true); runtime.time = findClass("UnityEngine.Time", true);
    runtime.eventSystem = findClass("UnityEngine.EventSystems.EventSystem", true); runtime.pointerData = findClass("UnityEngine.EventSystems.PointerEventData", true);
    runtime.raycastResult = findClass("UnityEngine.EventSystems.RaycastResult", true);
    ready = true; lastError = "";
    send({ type: "unity-ui-ready", bridgeVersion: BRIDGE_VERSION, agentVersion: AGENT_VERSION, unityVersion: Il2Cpp.unityVersion, screen: metadata() });
  }
  var mainDispatcher = null, mainBootstrap = null, mainIdentityProof = null, cachedMainRequested = false;
  function bootstrapMainDispatcher() {
    if (mainBootstrap) return mainBootstrap;
    // This is the only use of bridge 0.9.1's cold main scheduler. The host has
    // already independently identified the native engine-loop thread with
    // debuggerd and /proc; attachedThreads[0] is never accepted as proof.
    mainBootstrap = Il2Cpp.perform(function () {
      var proof = globalThis.QA_EXPECTED_UNITY_MAIN;
      var tid = Process.getCurrentThreadId();
      if (!proof || proof.pid !== QA_IDENTITY.pid || !Number.isInteger(proof.tid) ||
          proof.tid <= 0 || proof.tid !== tid || proof.comm !== "UnityMain" ||
          proof.source !== "native-debuggerd-engine-loop-and-proc-comm")
        throw new Error("Independent native Unity main-thread proof does not match this callback");
      var actualComm = File.readAllText("/proc/self/task/" + tid + "/comm").trim();
      if (actualComm !== proof.comm) throw new Error("Native Unity thread identity changed before bootstrap");
      mainIdentityProof = {pid:proof.pid,tid:tid,comm:actualComm,source:proof.source,
        nativeBacktraceSha256:proof.nativeBacktraceSha256};
      mainDispatcher = CachedMainThreadDispatcher.createIl2CppAdapter(
        {Il2Cpp:Il2Cpp,Process:Process,Script:Script,Frida:Frida,NULL:NULL},
        {expectedMainTid:tid,timeoutMs:10000,maxBatch:4});
      mainDispatcher.installOnCurrentMainThread();
      if (!ready) initialize();
      return true;
    }, "main");
    return mainBootstrap;
  }
  function onMain(action) {
    // Intro measurement retains the already validated observer path. The host
    // activates the cached dispatcher only at quiescent Title, after paired
    // timing and independent native stack collection, before the login tap.
    if (!cachedMainRequested) return Il2Cpp.perform(function () { if (!ready) initialize(); return action(); }, "main");
    return bootstrapMainDispatcher().then(function () { return mainDispatcher.dispatch(action); });
  }
  globalThis.QA_MVDUMP_HOST = Object.freeze({onMain: onMain, dispatcherStatus: function () { return mainDispatcher ? mainDispatcher.status() : null; }, cachedRequested: function () { return cachedMainRequested; }, findClass: findClass, allOfType: allOfType, exists: exists, active: active, maybe: maybe, call: call, overloaded: overloaded, field: field, numericField: numericField, transform: transform, gameObject: gameObject, hierarchy: hierarchy, instanceId: instanceId, fullType: fullType, metadata: metadata, nativeFeatureState: nativeFeatureState, mvReadField: mvReadField, mvBacking: mvBacking, mvNumber: mvNumber});
  rpc.exports = {
    enablecached: function (proof) {
      if (cachedMainRequested || introPending || initPending || introTimer)
        throw new Error("Cached main bootstrap requires once-only quiescent observer");
      globalThis.QA_EXPECTED_UNITY_MAIN = proof;
      cachedMainRequested = true;
      return onMain(function () { return {dispatcher:mainDispatcher.status(),screen:metadata(),mainIdentityProof:mainIdentityProof}; });
    },
    beginintrotrace: function () { return beginIntroTrace(); },
    endintrotrace: function () { return endIntroTrace(); },
    status: function () { return { ready: ready, lastError: lastError, initializing: initPending,
      bridgeVersion: BRIDGE_VERSION, agentVersion: AGENT_VERSION, fridaVersion: QA_IDENTITY.fridaVersion,
      pid: QA_IDENTITY.pid, architecture: QA_IDENTITY.architecture, pendingManagedIntroWork:introPending, introTimerActive:!!introTimer,
      dispatcher:mainDispatcher ? mainDispatcher.status() : null, mainIdentityProof:mainIdentityProof }; },
    dispose: function () {
      endIntroTrace();
      if (introPending || initPending) throw new Error("QA reads must quiesce before observer disposal");
      return mainDispatcher ? mainDispatcher.dispose(false) : {redirected:true,handlesFreed:0};
    },
    initialize: function () { return onMain(function () { return metadata(); }); },
    snapshot: function (options) { return onMain(function () { return snapshot(options || {}); }); },
    features: function () { return onMain(function () { return { timestampMs:Date.now(), screen:metadata(), features:featureState() }; }); },
    pick: function (query) { return onMain(function () { return choose(query || {}); }); },
    pickmv: function (query) { return onMain(function () { return pickExistingMvTarget(query || {}); }); },
    classes: function (pattern, maximum) {
      return onMain(function () {
        var needle = normalize(pattern || "button"), result = [], limit = Math.min(500, Math.max(1, Number(maximum) || 100));
        Il2Cpp.domain.assemblies.forEach(function (assembly) {
          if (result.length >= limit) return;
          assembly.image.classes.forEach(function (klass) {
            if (result.length >= limit) return;
            var name = klass.namespace ? klass.namespace + "." + klass.name : klass.name;
            if (normalize(name).indexOf(needle) >= 0) result.push({ name: name, assembly: assembly.name,
              parent: klass.parent ? klass.parent.namespace + "." + klass.parent.name : null });
          });
        }); return result;
      });
    }
  };
  // A fresh settled-Home host proves native Unity TID before enabling cached
  // reads. Do not run an unasserted cold initializer in that QA-only mode.
  if (globalThis.QA_CACHED_BOOTSTRAP_ONLY === true) return;
  setImmediate(function () {
    initPending = true;
    onMain(function () { return true; }).catch(function (error) { ready = false; lastError = String(error); send({ type: "unity-ui-error", error: lastError }); })
      .finally(function () { initPending = false; });
  });
}());

;
/* qa-mvdump: read-only runtime value dump of the playing MV (sifas-mv-runtime-dump/1).
 *
 * Appended to the r8 observer bundle by build_mvdump_agent.py, in the SAME Frida script, so
 * every Unity call runs on UnityMain through the observer's proven cached dispatcher
 * (globalThis.QA_MVDUMP_HOST.onMain -> mainDispatcher.dispatch). No second script,
 * delegate, GC handle, bootstrap or scheduler exists here.
 *
 * Read-only by construction:
 *  - every Unity call goes through inv(): deny pattern first, then an exact allowlist of
 *    UnityEngine getters / pure statics (ALLOW), fixed parameter signatures (SIG), a
 *    holder-type check, and m_CachedPtr != 0 before any instance call;
 *  - LLAS (game) objects are only read through fields, never through their methods;
 *  - indexes are bounds-checked (GetChild < childCount, blend shapes < blendShapeCount,
 *    material Get* only after HasProperty);
 *  - no Il2Cpp object survives a callback: roots are re-enumerated in every action and
 *    cursors are plain JSON. Caches hold metadata (classes, methods, fields), ints
 *    (shader property ids) and strings (paths) only;
 *  - actions are plain synchronous functions returning plain JSON (never a thenable);
 *  - the RPCs refuse unless the cached dispatcher is READY, so the cold
 *    Il2Cpp.perform(..., 'main') path is never taken;
 *  - every action is bounded: object caps per type and a soft/hard time budget.
 * Managed exceptions are prevented by these rules; JS-level and bridge raise() errors are
 * caught per section and recorded as {at, error}.
 */
(function () {
  "use strict";
  var H = globalThis.QA_MVDUMP_HOST;
  if (!H) throw new Error("MVDUMP_HOST_MISSING");
  var EXT_VERSION = 2;
  var PARTS = ["frame", "census", "quality", "fovmodNative", "renderers", "materials", "lightingRefs", "members",
    "springs", "stageNodes", "particles", "post"];
  // Defaults only: the sampler sends the budgets it uses (MV_RUNTIME_DUMP_FRAME_BUDGET_MS /
  // MV_RUNTIME_DUMP_FULL_BUDGET_MS, recorded in header.budgets) with every action.
  var BUDGET = { frame: { soft: 60, hard: 150 }, full: { soft: 80, hard: 200 } };
  var CAPS = { directors: 8, cameras: 16, camerasDetailed: 8, correctors: 8, cameraWork: 4, lights: 16, globals: 20,
    anchors: 8, members: 9, censusNodes: 400, censusDepth: 6, censusChunk: 80, components: 12, renderers: 400,
    rendererChunk: 24, materials: 256, materialChunk: 8, properties: 48, keywords: 16, bonesPerMember: 24,
    blendShapesInspected: 64, blendShapes: 24, swingBones: 64, stageNodes: 256, stageChunk: 64, stageDepth: 12,
    particles: 160, particleChunk: 40, fields: 48, fieldDepth: 2, arrayItems: 8, stringChars: 120, enumerate: 8192,
    errors: 24, holders: 8, lightingPerClass: 16, slots: 8 };

  // ------------------------------------------------------------------ policy
  var DENY = /^set_|^Set[A-Z]|^(Play|Pause|Stop|Resume|Evaluate|RebuildGraph|DeferredEvaluate|Simulate|Emit|Clear|Render|RenderWithShader|Destroy|DestroyImmediate|Instantiate|AddComponent|SendMessage|BroadcastMessage|Invoke|InvokeRepeating|StartCoroutine|GetParticles|GetPropertyBlock|BakeMesh|Update|LateUpdate)$|^get_(material|materials|mesh)$/;
  var ALLOW = {
    "UnityEngine.Time": ["get_frameCount", "get_time", "get_unscaledTime", "get_deltaTime", "get_timeScale", "get_realtimeSinceStartup"],
    "UnityEngine.Screen": ["get_width", "get_height", "get_orientation"],
    "UnityEngine.GameObject": ["Find", "get_activeSelf", "get_activeInHierarchy", "get_transform", "get_layer"],
    "UnityEngine.Shader": ["PropertyToID", "GetGlobalFloat", "GetGlobalVector", "GetGlobalVectorArray"],
    "UnityEngine.RenderSettings": ["get_fog", "get_fogMode", "get_fogColor", "get_fogDensity", "get_fogStartDistance",
      "get_fogEndDistance", "get_ambientMode", "get_ambientSkyColor", "get_ambientEquatorColor", "get_ambientGroundColor",
      "get_ambientIntensity", "get_ambientLight", "get_reflectionIntensity", "get_skybox"],
    "UnityEngine.QualitySettings": ["get_activeColorSpace", "get_vSyncCount", "get_antiAliasing"],
    "UnityEngine.Application": ["get_targetFrameRate"],
    "UnityEngine.Object": ["GetInstanceID", "get_name"],
    "UnityEngine.Component": ["get_gameObject", "get_transform", "GetComponents", "GetComponent"],
    "UnityEngine.Behaviour": ["get_enabled", "get_isActiveAndEnabled"],
    "UnityEngine.Transform": ["get_position", "get_rotation", "get_lossyScale", "get_localPosition", "get_localRotation",
      "get_localScale", "get_parent", "get_childCount", "GetChild", "Find", "GetSiblingIndex"],
    "UnityEngine.Camera": ["get_fieldOfView", "get_aspect", "get_nearClipPlane", "get_farClipPlane", "get_orthographic",
      "get_orthographicSize", "get_usePhysicalProperties", "get_focalLength", "get_lensShift", "get_projectionMatrix",
      "get_worldToCameraMatrix", "get_rect", "get_pixelRect", "get_pixelWidth", "get_pixelHeight", "get_depth",
      "get_clearFlags", "get_backgroundColor", "get_cullingMask", "get_allowHDR", "get_allowMSAA", "get_depthTextureMode",
      "get_targetTexture"],
    "UnityEngine.Texture": ["get_width", "get_height"],
    "UnityEngine.RenderTexture": ["get_format"],
    "UnityEngine.Playables.PlayableDirector": ["get_time", "get_duration", "get_state", "get_timeUpdateMode",
      "get_extrapolationMode", "get_playableAsset"],
    "UnityEngine.Renderer": ["get_enabled", "get_isVisible", "get_bounds", "get_sharedMaterials", "get_lightmapIndex",
      "get_lightmapScaleOffset", "get_sortingOrder"],
    "UnityEngine.SkinnedMeshRenderer": ["get_sharedMesh", "GetBlendShapeWeight"],
    "UnityEngine.MeshFilter": ["get_sharedMesh"],
    "UnityEngine.Mesh": ["get_blendShapeCount", "GetBlendShapeName"],
    "UnityEngine.Material": ["get_shader", "get_renderQueue", "get_shaderKeywords", "HasProperty", "GetFloat", "GetColor",
      "GetVector", "GetTexture", "GetTextureScale", "GetTextureOffset"],
    "UnityEngine.Light": ["get_type", "get_color", "get_intensity", "get_range", "get_spotAngle", "get_shadows", "get_cullingMask"],
    "UnityEngine.ParticleSystem": ["get_isPlaying", "get_isEmitting", "get_isPaused", "get_particleCount", "get_time",
      "get_randomSeed", "get_useAutoRandomSeed"]
  };
  var INT = ["System.Int32"];
  var SIG = {
    "UnityEngine.GameObject::Find": ["System.String"], "UnityEngine.Shader::PropertyToID": ["System.String"],
    "UnityEngine.Shader::GetGlobalFloat": INT, "UnityEngine.Shader::GetGlobalVector": INT,
    "UnityEngine.Shader::GetGlobalVectorArray": INT, "UnityEngine.Component::GetComponents": ["System.Type"],
    "UnityEngine.Component::GetComponent": ["System.Type"], "UnityEngine.Transform::GetChild": INT,
    "UnityEngine.Transform::Find": ["System.String"], "UnityEngine.SkinnedMeshRenderer::GetBlendShapeWeight": INT,
    "UnityEngine.Mesh::GetBlendShapeName": INT, "UnityEngine.Material::HasProperty": INT, "UnityEngine.Material::GetFloat": INT,
    "UnityEngine.Material::GetColor": INT, "UnityEngine.Material::GetVector": INT, "UnityEngine.Material::GetTexture": INT,
    "UnityEngine.Material::GetTextureScale": INT, "UnityEngine.Material::GetTextureOffset": INT
  };
  var STATIC_CLASSES = { "UnityEngine.Time": 1, "UnityEngine.Screen": 1, "UnityEngine.Shader": 1, "UnityEngine.RenderSettings": 1,
    "UnityEngine.QualitySettings": 1, "UnityEngine.Application": 1 };
  var STATIC_METHODS = { "UnityEngine.GameObject::Find": 1 };

  // Class candidates (<= 4 per class). The probe resolves them once; sample() reuses the result.
  var COMPONENTS = ["LiveCoreCameraManager", "LiveCoreCamera", "LiveCoreCameraWork", "CameraAspectCorrector",
    "LiveCoreOverlayCamera", "LiveSplitScreenEffect", "LiveCoreMemberManager", "LiveCoreMember", "LiveCoreMemberAmbient",
    "LiveCoreMemberRimlight", "LiveCoreMemberNodeScaling", "LiveCoreStageAmbient", "LiveCoreStageModel",
    "LiveCoreStageEmissive", "LiveCoreStageEffect", "LiveCoreStagePenlight", "LiveCoreStageDisplay",
    "LiveCoreStageFlashLight", "LiveCoreStageColoring", "LivePropAmbient", "LivePropRimlight", "LivePauseMediator"];
  var CLASS_TABLE = [
    { key: "Camera", candidates: ["UnityEngine.Camera"], unity: true },
    { key: "PlayableDirector", candidates: ["UnityEngine.Playables.PlayableDirector"], unity: true },
    { key: "Light", candidates: ["UnityEngine.Light"], unity: true },
    { key: "ParticleSystem", candidates: ["UnityEngine.ParticleSystem"], unity: true },
    { key: "LiveDirector", candidates: ["LLAS.Scene.Live.LiveDirector", "LLAS.Scene.LiveMv.LiveDirector", "LiveDirector"] },
    { key: "LiveDirectorBase", candidates: ["LLAS.Scene.Live.LiveDirectorBase", "LLAS.Scene.LiveMv.LiveDirectorBase", "LiveDirectorBase"] },
    { key: "LiveMvScene", candidates: ["LLAS.Scene.Live.LiveMvScene", "LLAS.Scene.LiveMv.LiveMvScene", "LiveMvScene"] }
  ].concat(COMPONENTS.map(function (name) {
    return { key: name, candidates: ["LLAS.Scene.Live.Components." + name] };
  })).concat(["LiveMusicMachine", "SwingBoneManager", "SwingBone", "BodyPartManager", "MemberSpotLightShaft",
    "LiveQualitySettingVO"].map(function (name) {
    var first = name === "LiveMusicMachine" ? "LLAS.Scene.Live.Components." : name === "LiveQualitySettingVO" ? "LLAS.DM.ValueObject." : "LLAS.Components.Members.";
    var list = [first + name, "LLAS.Scene.Live.Components." + name, "LLAS.Scene.Live." + name, "LLAS." + name, name];
    var unique = [];
    list.forEach(function (c) { if (unique.indexOf(c) < 0) unique.push(c); });
    return { key: name, candidates: unique.slice(0, 4) };
  }));
  var CLASS_KEYS = {};
  CLASS_TABLE.forEach(function (entry) { CLASS_KEYS[entry.key] = entry; });

  // Integer enum names (Unity 2018.4).
  var ENUMS = {
    PlayState: { 0: "Paused", 1: "Playing", 2: "Delayed" },
    DirectorUpdateMode: { 0: "DSPClock", 1: "GameTime", 2: "UnscaledGameTime", 3: "Manual" },
    DirectorWrapMode: { 0: "Hold", 1: "Loop", 2: "None" },
    CameraClearFlags: { 1: "Skybox", 2: "SolidColor", 3: "Depth", 4: "Nothing" },
    DepthTextureMode: { 0: "None", 1: "Depth", 2: "DepthNormals", 3: "Depth|DepthNormals", 4: "MotionVectors", 5: "Depth|MotionVectors" },
    ScreenOrientation: { 0: "Unknown", 1: "Portrait", 2: "PortraitUpsideDown", 3: "LandscapeLeft", 4: "LandscapeRight", 5: "AutoRotation" },
    LightType: { 0: "Spot", 1: "Directional", 2: "Point", 3: "Area", 4: "Disc" },
    LightShadows: { 0: "None", 1: "Hard", 2: "Soft" },
    FogMode: { 1: "Linear", 2: "Exponential", 3: "ExponentialSquared" },
    AmbientMode: { 0: "Skybox", 1: "Trilight", 3: "Flat", 4: "Custom" },
    ColorSpace: { "-1": "Uninitialized", 0: "Gamma", 1: "Linear" },
    RenderTextureFormat: { 0: "ARGB32", 1: "Depth", 2: "ARGBHalf", 3: "Shadowmap", 4: "RGB565", 5: "ARGB4444", 6: "ARGB1555",
      7: "Default", 8: "ARGB2101010", 9: "DefaultHDR", 10: "ARGB64", 11: "ARGBFloat", 12: "RGFloat", 13: "RGHalf",
      14: "RFloat", 15: "RHalf", 16: "R8" }
  };
  var STRUCTS = { "UnityEngine.Vector2": ["vec2", 2], "UnityEngine.Vector3": ["vec3", 3], "UnityEngine.Vector4": ["vec4", 4],
    "UnityEngine.Quaternion": ["quat", 4], "UnityEngine.Color": ["color", 4], "UnityEngine.Rect": ["rect", 4],
    "UnityEngine.Matrix4x4": ["mat4", 16], "UnityEngine.Bounds": ["bounds", 6] };
  var SECRET_LIKE = /pass|token|secret|session|auth|account|user|mail|device|key/i;
  function nameLike(field) { return /(^|[_<.])(name|path|id)(>|$)/i.test(field) || /[a-z](Name|Path|Id)(>|$)/.test(field); }
  var PRIMITIVE = { "System.Single": "f32", "System.Double": "f64", "System.Int32": "i32", "System.UInt32": "u32",
    "System.Int16": "i16", "System.UInt16": "u16", "System.Byte": "u8", "System.SByte": "i8", "System.Char": "char",
    "System.Boolean": "bool", "System.Int64": "i64", "System.UInt64": "u64" };
  var STATIC_GLOBALS = ["_Beat", "_MusicTime", "_SelfTime", "_ColorsLength", "_RenderTextureResolution", "_Time",
    "_AmbientColor", "_TintColor", "_BlendColor", "_RimlightColor", "_RimlightDirection", "_RimglightIntensity", "_RimglightPower"];
  var DEFAULT_LIGHTING = ["LiveCoreMemberAmbient", "LiveCoreMemberRimlight", "LiveCoreStageAmbient", "LiveCoreStageModel",
    "LivePropAmbient", "LivePropRimlight", "LiveCoreStagePenlight", "LiveCoreStageColoring", "LiveCoreStageFlashLight",
    "LiveCoreStageDisplay"];
  var POST_CLASS = /Post|Bloom|DepthOfField|Flare/;

  // ------------------------------------------------------------------ caches (metadata / ints / strings only)
  var methodCache = {}, isaCache = {}, layoutCache = {}, propertyIds = {}, resolved = {}, pathCache = {}, pathCacheSize = 0;
  var PATH_TTL_MS = 15000, PATH_CACHE_MAX = 4096;
  var offsets = null;

  function requireReady() {
    var s = H.dispatcherStatus();
    if (!H.cachedRequested() || !s || s.state !== "READY")
      throw new Error("MVDUMP_DISPATCHER_NOT_READY:" + (s ? s.state + "/" + s.lastCode : "none"));
  }
  function short(error) { return String(error && error.message || error).slice(0, 160); }
  function Ctx(kind, options) {
    var b = options.budget || {}, d = kind === "frame" ? BUDGET.frame : BUDGET.full;
    this.t0 = Date.now();
    this.soft = typeof b.soft === "number" ? b.soft : d.soft;
    this.hard = typeof b.hard === "number" ? b.hard : d.hard;
    this.calls = 0; this.objects = 0; this.truncated = false; this.truncatedSections = []; this.nonFinite = [];
    this.errors = []; this.classBudget = 8; this.arrays = options.arrays === true; this.memo = {};
  }
  Ctx.prototype.elapsed = function () { return Date.now() - this.t0; };
  Ctx.prototype.pastSoft = function () { return this.elapsed() >= this.soft; };
  Ctx.prototype.pastHard = function () { return this.elapsed() >= this.hard; };
  Ctx.prototype.cut = function (section) {
    this.truncated = true;
    if (this.truncatedSections.indexOf(section) < 0) this.truncatedSections.push(section);
  };
  Ctx.prototype.err = function (at, error) {
    if (this.errors.length < CAPS.errors) this.errors.push({ at: String(at).slice(0, 80), error: short(error) });
  };
  Ctx.prototype.bad = function (path) { if (this.nonFinite.length < 64) this.nonFinite.push(path); };
  Ctx.prototype.cost = function () {
    return { elapsedMs: this.elapsed(), calls: this.calls, objects: this.objects, truncated: this.truncated,
      truncatedSections: this.truncatedSections.slice(), budgetMs: { soft: this.soft, hard: this.hard } };
  };

  // ------------------------------------------------------------------ low level
  function initOffsets() {
    if (offsets) return offsets;
    var object = H.findClass("UnityEngine.Object", true), cached = null, id = null;
    try { cached = object.field("m_CachedPtr").offset; } catch (_) {}
    try { id = object.field("m_InstanceID").offset; } catch (_) {}
    if (typeof cached !== "number") throw new Error("MVDUMP_LIVENESS_UNAVAILABLE: UnityEngine.Object.m_CachedPtr");
    offsets = { cachedPtr: cached, instanceId: typeof id === "number" ? id : null, object: object };
    return offsets;
  }
  function isObj(value) {
    return !!value && typeof value.isNull === "function" && !value.isNull() && value.handle && typeof value.handle.add === "function";
  }
  // A UnityEngine.Object whose native counterpart still exists (m_CachedPtr != 0).
  function alive(value) {
    if (!isObj(value)) return false;
    return !value.handle.add(initOffsets().cachedPtr).readPointer().isNull();
  }
  function iid(value) {
    if (!isObj(value)) return null;
    var o = initOffsets();
    if (o.instanceId !== null) return value.handle.add(o.instanceId).readS32();
    return alive(value) ? Number(inv(null, "UnityEngine.Object", "GetInstanceID", value, [])) : null;
  }
  function klassName(klass) { return klass ? (klass.namespace ? klass.namespace + "." + klass.name : klass.name) : null; }
  function isA(value, klass) {
    if (!isObj(value) || !klass) return false;
    var c = value.class, key = c.handle.toString() + "|" + klass.handle.toString(), v = isaCache[key];
    if (v === undefined) { v = c.handle.equals(klass.handle) || !!c.isSubclassOf(klass, false); isaCache[key] = v; }
    return v;
  }
  function classIsA(klass, base) {
    if (!klass || !base) return false;
    var key = klass.handle.toString() + "|" + base.handle.toString(), v = isaCache[key];
    if (v === undefined) { v = klass.handle.equals(base.handle) || !!klass.isSubclassOf(base, false); isaCache[key] = v; }
    return v;
  }
  function method(className, name, argc) {
    var key = className + "::" + name + "/" + argc;
    if (methodCache.hasOwnProperty(key)) return methodCache[key];
    if (DENY.test(name)) throw new Error("MVDUMP_POLICY_DENY:" + className + "::" + name);
    if (!/^UnityEngine(\.|$)/.test(className)) throw new Error("MVDUMP_POLICY_NAMESPACE:" + className);
    if (!ALLOW[className] || ALLOW[className].indexOf(name) < 0) throw new Error("MVDUMP_POLICY_NOT_ALLOWED:" + className + "::" + name);
    var types = SIG[className + "::" + name] || [];
    if (types.length !== argc) throw new Error("MVDUMP_POLICY_SIGNATURE:" + className + "::" + name + "/" + argc);
    var klass = H.findClass(className, true), m = null;
    if (klass) {
      m = klass.tryMethod(name, argc) || null;
      if (m && types.length) m = m.tryOverload.apply(m, types) || null;
    }
    var entry = null;
    if (m) {
      var declaring = m.class;
      if (!/^UnityEngine(\.|$)/.test(declaring.namespace || "")) throw new Error("MVDUMP_POLICY_DECLARING:" + klassName(declaring));
      var wantStatic = !!(STATIC_CLASSES[className] || STATIC_METHODS[className + "::" + name] || (name === "PropertyToID"));
      if (!!m.isStatic !== wantStatic) throw new Error("MVDUMP_POLICY_STATIC:" + className + "::" + name);
      entry = { m: m, klass: klass, isStatic: !!m.isStatic };
    }
    methodCache[key] = entry;
    return entry;
  }
  // The one choke point for Unity calls. Returns null for a dead holder (never invoked).
  function inv(ctx, className, name, holder, args) {
    args = args || [];
    var entry = method(className, name, args.length);
    if (!entry) throw new Error("MVDUMP_METHOD_UNAVAILABLE:" + className + "::" + name);
    if (entry.isStatic) {
      if (ctx) ctx.calls++;
      return entry.m.invoke.apply(entry.m, args);
    }
    if (!alive(holder)) return null;
    if (!isA(holder, entry.klass)) throw new Error("MVDUMP_HOLDER_TYPE:" + H.fullType(holder) + " is not " + className);
    if (ctx) ctx.calls++;
    var bound = entry.m.withHolder(holder);
    return bound.invoke.apply(bound, args);
  }
  // inv() with a per-value error boundary (records the error, returns null).
  function g(ctx, className, name, holder, convert, args) {
    try {
      var value = inv(ctx, className, name, holder, args);
      return convert ? convert(value) : value;
    } catch (error) { ctx.err(className.replace("UnityEngine.", "") + "." + name, error); return null; }
  }
  function str(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "string") return value;
    if (typeof value.isNull === "function" && value.isNull()) return null;
    var length = typeof value.length === "number" ? value.length : 0;
    if (length > 4096) return null;
    return value.content === undefined || value.content === null ? null : String(value.content);
  }
  function nameOf(ctx, object) { return str(inv(ctx, "UnityEngine.Object", "get_name", object, [])); }
  function bool(value) { return value === null || value === undefined ? null : !!value; }
  function enumInt(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === "number") return isFinite(value) ? value : null;
    if (typeof value === "boolean") return value ? 1 : 0;
    try { var n = Number(value.field("value__").value); return isFinite(n) ? n : null; } catch (_) { return null; }
  }
  function en(table) {
    return function (value) {
      var v = enumInt(value);
      return v === null ? null : { v: v, n: ENUMS[table] && ENUMS[table][v] !== undefined ? ENUMS[table][v] : null };
    };
  }
  function num(ctx, value, path, digits) {
    if (value === null || value === undefined) return null;
    if (typeof value === "boolean") return value;
    var n = typeof value === "number" ? value : Number(value);
    if (!isFinite(n)) { ctx.bad(path); return null; }
    if (Math.floor(n) === n && Math.abs(n) < 9007199254740992) return n;
    return Number(n.toPrecision(digits || 7));
  }
  function raw(ctx, value, count, path, digits) {
    if (!value || !value.handle || (typeof value.isNull === "function" && value.isNull())) return null;
    var out = [], h = value.handle;
    for (var i = 0; i < count; i++) out.push(num(ctx, h.add(4 * i).readFloat(), path + "[" + i + "]", digits || 9));
    return out;
  }
  function rd(ctx, count, digits) { return function (value) { return raw(ctx, value, count, "v", digits); }; }
  function items(array, cap) {
    var out = [];
    out.total = 0;
    if (!array || (typeof array.isNull === "function" && array.isNull())) return out;
    var n = Number(array.length);
    out.total = n;
    for (var i = 0; i < n && i < cap; i++) out.push(array.get(i));
    return out;
  }
  function stripName(name) { return String(name === null ? "?" : name).replace(/\(Clone\)$/, "").replace(/ \(Instance\)$/, ""); }

  // ------------------------------------------------------------------ classes
  function lookupEntry(entry, ctx) {
    for (var i = 0; i < entry.candidates.length && i < 4; i++) {
      var klass = H.findClass(entry.candidates[i], true);
      if (klass) return { klass: klass, fullName: entry.candidates[i] };
    }
    return null;
  }
  function cls(ctx, key) {
    if (resolved.hasOwnProperty(key)) return resolved[key] ? H.findClass(resolved[key], true) : null;
    var entry = CLASS_KEYS[key] || { key: key, candidates: [key] };
    if (ctx && ctx.classBudget-- <= 0) { ctx.err("class:" + key, "MVDUMP_CLASS_UNRESOLVED_BUDGET (run mvruntimeprobe first)"); return null; }
    var found = lookupEntry(entry, ctx);
    resolved[key] = found ? found.fullName : null;
    return found ? found.klass : null;
  }
  function unityObjectClass(klass) { return classIsA(klass, initOffsets().object); }
  // Snapshot of live instances of a UnityEngine.Object class (FindObjectsOfTypeAll).
  function instances(ctx, klass, cap) {
    if (!klass || !unityObjectClass(klass)) return [];
    ctx.calls++;
    var list = items(H.allOfType(klass), cap || CAPS.enumerate), out = [];
    out.total = list.total;
    for (var i = 0; i < list.length; i++) if (alive(list[i])) out.push(list[i]);
    return out;
  }
  function activeGo(ctx, object) {
    var go = isA(object, H.findClass("UnityEngine.GameObject", true)) ? object : refValue(inv(ctx, "UnityEngine.Component", "get_gameObject", object, []));
    return go ? !!inv(ctx, "UnityEngine.GameObject", "get_activeInHierarchy", go, []) : false;
  }
  function trOf(ctx, object) {
    if (!alive(object)) return null;
    if (isA(object, H.findClass("UnityEngine.Transform", true))) return object;
    if (isA(object, H.findClass("UnityEngine.GameObject", true))) return refValue(inv(ctx, "UnityEngine.GameObject", "get_transform", object, []));
    return refValue(inv(ctx, "UnityEngine.Component", "get_transform", object, []));
  }
  function goIid(ctx, object) {
    if (!alive(object)) return null;
    if (isA(object, H.findClass("UnityEngine.GameObject", true))) return iid(object);
    return iid(inv(ctx, "UnityEngine.Component", "get_gameObject", object, []));
  }
  // Root-first path with (Clone)/( Instance) stripped; cached per Transform instanceId (strings only).
  function pathInfo(ctx, object) {
    var tr = trOf(ctx, object);
    if (!tr) return { path: null, rawPath: null, segments: [] };
    var id = iid(tr), now = Date.now(), cached = pathCache[id];
    if (cached && now - cached.t < PATH_TTL_MS) return cached;
    var names = [], cur = tr, guard = 0;
    while (isObj(cur) && guard++ < 48) {
      names.push(nameOf(ctx, cur));
      cur = refValue(inv(ctx, "UnityEngine.Transform", "get_parent", cur, []));
    }
    names.reverse();
    var segments = names.map(stripName);
    var info = { path: "/" + segments.join("/"), rawPath: "/" + names.map(function (n) { return n === null ? "?" : n; }).join("/"),
      segments: segments, t: now };
    if (pathCacheSize >= PATH_CACHE_MAX) { pathCache = {}; pathCacheSize = 0; }
    if (!pathCache[id]) pathCacheSize++;
    pathCache[id] = info;
    return info;
  }
  function withPath(target, info) {
    target.path = info.path;
    if (info.rawPath !== info.path) target.rawPath = info.rawPath;
    return target;
  }
  function fv(object, name) {
    if (!isObj(object)) return undefined;
    try { return object.field(name).value; } catch (_) { return undefined; }
  }
  function fieldAny(object, names) {
    for (var i = 0; i < names.length; i++) {
      var value = fv(object, names[i]);
      if (value !== undefined) return { name: names[i], value: value };
    }
    return null;
  }
  function backingNames(name) {
    var upper = name.charAt(0).toUpperCase() + name.slice(1);
    return [name, "<" + upper + ">k__BackingField", "_" + name, "m_" + upper];
  }
  function refValue(value) { return isObj(value) ? value : null; }
  function numberField(object, names) {
    var found = fieldAny(object, names);
    if (!found) return null;
    var v = found.value;
    if (typeof v === "number" || typeof v === "boolean") return v;
    var e = enumInt(v);
    return e;
  }
  function resolvePath(ctx, path) {
    var parts = String(path).replace(/^\//, "").split("/");
    var root = inv(ctx, "UnityEngine.GameObject", "Find", null, [Il2Cpp.string("/" + parts[0])]);
    if (!alive(root)) return null;
    var tr = inv(ctx, "UnityEngine.GameObject", "get_transform", root, []);
    if (parts.length === 1) return tr;
    return refValue(inv(ctx, "UnityEngine.Transform", "Find", tr, [Il2Cpp.string(parts.slice(1).join("/"))]));
  }

  // ------------------------------------------------------------------ generic field reader (schema section 5)
  function layoutOf(klass) {
    var key = klass.handle.toString();
    if (layoutCache[key]) return layoutCache[key];
    var out = [], k = klass, guard = 0;
    while (k && guard++ < 8) {
      var ns = k.namespace || "";
      if (/^(UnityEngine|System|TMPro)(\.|$)/.test(ns)) break;
      var fields = k.fields || [];
      for (var i = 0; i < fields.length; i++) {
        var f = fields[i];
        if (f.isStatic) continue;
        out.push({ field: f, name: f.name, typeName: f.type.name });
      }
      k = k.parent;
    }
    layoutCache[key] = out;
    return out;
  }
  function structValue(ctx, value, path) {
    var typeName = value.type ? value.type.name : null, klass = value.type ? value.type.class : null;
    if (klass && klass.isEnum) return { t: "enum", v: { v: enumInt(value), n: null } };
    var shape = STRUCTS[typeName];
    if (shape) return { t: shape[0], v: raw(ctx, value, shape[1], path, 9) };
    if (typeName === "UnityEngine.Color32") {
      var h = value.handle;
      return { t: "color32", v: [h.readU8(), h.add(1).readU8(), h.add(2).readU8(), h.add(3).readU8()] };
    }
    if (/^System\.Nullable`1/.test(typeName || "")) {
      var has = fv(value, "has_value");
      return { t: "nullable", v: has === true ? convert(ctx, fv(value, "value"), "value", 2, path) : null };
    }
    return { t: "struct", class: typeName };
  }
  function convert(ctx, value, fieldName, depth, path, typeName) {
    if (value === undefined) return { t: "unreadable", v: null };
    if (value === null) return { t: "null", v: null };
    if (typeof value === "boolean") return { t: "bool", v: value };
    if (typeof value === "number") return { t: PRIMITIVE[typeName] || (Math.floor(value) === value ? "int" : "f32"), v: num(ctx, value, path, 7) };
    if (typeof NativePointer !== "undefined" && value instanceof NativePointer) return { t: "ptr", v: null };
    if (typeof Int64 !== "undefined" && (value instanceof Int64 || (typeof UInt64 !== "undefined" && value instanceof UInt64)))
      return { t: "i64", v: num(ctx, Number(value.toString()), path, 15) };
    if (value instanceof Il2Cpp.String) {
      if (value.isNull()) return { t: "str", v: null };
      if (!nameLike(fieldName) || SECRET_LIKE.test(fieldName)) return { t: "str", v: null, skipped: true };
      var s = str(value);
      return { t: "str", v: s === null ? null : s.slice(0, CAPS.stringChars) };
    }
    if (value instanceof Il2Cpp.Array) {
      if (value.isNull()) return { t: "array", v: null };
      var list = items(value, CAPS.arrayItems), out = [];
      for (var i = 0; i < list.length; i++) out.push(depth < CAPS.fieldDepth ? convert(ctx, list[i], fieldName, CAPS.fieldDepth, path + "[" + i + "]") : null);
      return { t: "array", n: list.total, items: out };
    }
    if (value instanceof Il2Cpp.ValueType) return structValue(ctx, value, path);
    if (value instanceof Il2Cpp.Object) {
      if (value.isNull()) return { t: "ref", v: null };
      var klass = value.class, name = klassName(klass);
      if (unityObjectClass(klass)) {
        var live = alive(value);
        return { t: "ref", v: { ref: iid(value), name: live ? nameOf(ctx, value) : null, class: name, dead: !live || undefined } };
      }
      if (/^System\.Collections\.Generic\.List`1/.test(name || "") || (klass.namespace === "System.Collections.Generic" && /^List`1/.test(klass.name))) {
        var size = fv(value, "_size"), backing = fv(value, "_items"), entries = [];
        var listed = backing instanceof Il2Cpp.Array ? items(backing, Math.min(CAPS.arrayItems, Number(size) || 0)) : [];
        for (var j = 0; j < listed.length; j++) entries.push(depth < CAPS.fieldDepth ? convert(ctx, listed[j], fieldName, CAPS.fieldDepth, path + "[" + j + "]") : null);
        return { t: "list", n: typeof size === "number" ? size : null, items: entries };
      }
      if (/^System(\.|$)/.test(klass.namespace || "") || depth >= CAPS.fieldDepth) return { t: "obj", class: name };
      return { t: "obj", class: name, fields: readFields(ctx, value, depth + 1, path) };
    }
    return { t: typeof value, v: null };
  }
  function readFields(ctx, object, depth, path, skip) {
    if (!isObj(object)) return null;
    var layout = layoutOf(object.class), out = {}, count = 0;
    for (var i = 0; i < layout.length && count < CAPS.fields; i++) {
      var entry = layout[i];
      if (skip && skip.indexOf(entry.name) >= 0) continue;
      if (out.hasOwnProperty(entry.name)) continue;
      if (ctx.pastHard()) { ctx.cut("fields"); break; }
      var value;
      try { value = entry.field.withHolder(object).value; } catch (error) { out[entry.name] = { t: "unreadable", v: null }; count++; continue; }
      out[entry.name] = convert(ctx, value, entry.name, depth || 0, (path || "fields") + "." + entry.name, entry.typeName);
      count++;
    }
    return out;
  }

  // ------------------------------------------------------------------ readers
  function transformOf(ctx, tr, path, full) {
    var T = "UnityEngine.Transform";
    var out = { position: g(ctx, T, "get_position", tr, function (v) { return raw(ctx, v, 3, path + ".position", 9); }),
      rotation: g(ctx, T, "get_rotation", tr, function (v) { return raw(ctx, v, 4, path + ".rotation", 9); }),
      lossyScale: g(ctx, T, "get_lossyScale", tr, function (v) { return raw(ctx, v, 3, path + ".lossyScale", 9); }) };
    if (full) {
      out.localPosition = g(ctx, T, "get_localPosition", tr, function (v) { return raw(ctx, v, 3, path + ".localPosition", 9); });
      out.localRotation = g(ctx, T, "get_localRotation", tr, function (v) { return raw(ctx, v, 4, path + ".localRotation", 9); });
    }
    return out;
  }
  function liveDirectors(ctx) {
    if (ctx.memo.liveDirectors) return ctx.memo.liveDirectors;
    var klass = cls(ctx, "LiveDirector"), out = [];
    instances(ctx, klass, 32).forEach(function (object) { if (out.length < 4 && activeGo(ctx, object)) out.push(object); });
    ctx.memo.liveDirectors = out;
    return out;
  }
  function readDirectors(ctx) {
    var PD = H.findClass("UnityEngine.Playables.PlayableDirector", true), D = "UnityEngine.Playables.PlayableDirector";
    var held = {};
    liveDirectors(ctx).forEach(function (ld) {
      var found = fieldAny(ld, ["<TimelineDirector>k__BackingField", "timelineDirector", "playableDirector", "director"]);
      if (found && alive(found.value) && isA(found.value, PD)) held[iid(found.value)] = found.name;
    });
    var list = [], objects = instances(ctx, PD, 256);
    for (var i = 0; i < objects.length && list.length < CAPS.directors; i++) {
      var d = objects[i], id = iid(d);
      if (!held[id] && !activeGo(ctx, d)) continue;
      ctx.objects++;
      var p = "directors[" + list.length + "]", info = pathInfo(ctx, d);
      var asset = g(ctx, D, "get_playableAsset", d);
      var item = withPath({ key: "director:" + info.path }, info);
      item.instanceId = id; item.main = false;
      item.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", d, bool);
      item.time = g(ctx, D, "get_time", d, function (v) { return num(ctx, v, p + ".time", 9); });
      item.duration = g(ctx, D, "get_duration", d, function (v) { return num(ctx, v, p + ".duration", 9); });
      item.state = g(ctx, D, "get_state", d, en("PlayState"));
      item.timeUpdateMode = g(ctx, D, "get_timeUpdateMode", d, en("DirectorUpdateMode"));
      item.extrapolationMode = g(ctx, D, "get_extrapolationMode", d, en("DirectorWrapMode"));
      item.asset = alive(asset) ? nameOf(ctx, asset) : null;
      item.heldByLiveDirector = !!held[id];
      if (held[id]) item.heldBy = held[id];
      list.push({ item: item, object: d });
    }
    var main = list.filter(function (e) { return e.item.heldByLiveDirector; })[0];
    if (!main) {
      var playing = list.filter(function (e) { return e.item.state && e.item.state.v === 1; });
      var pool = playing.length ? playing : list;
      pool.sort(function (a, b) { return (b.item.duration || 0) - (a.item.duration || 0); });
      main = pool[0];
      if (main) main.item.mainBy = playing.length ? "playing-longest" : "longest";
    } else main.item.mainBy = "LiveDirector." + main.item.heldBy;
    if (main) main.item.main = true;
    return { list: list.map(function (e) { return e.item; }), main: main || null };
  }
  function musicMachine(ctx) {
    var candidates = [];
    liveDirectors(ctx).forEach(function (ld) {
      var found = fieldAny(ld, ["<MusicMachine>k__BackingField", "musicMachine", "liveMusicMachine"]);
      if (found && isObj(found.value)) candidates.push(found.value);
    });
    if (!candidates.length) {
      var klass = cls(ctx, "LiveMusicMachine");
      if (klass && unityObjectClass(klass)) instances(ctx, klass, 8).forEach(function (m) { candidates.push(m); });
    }
    return candidates[0] || null;
  }
  function readClock(ctx, directors) {
    var T = "UnityEngine.Time", main = directors && directors.main;
    var clock = { directorTime: main ? main.item.time : null,
      frameCount: g(ctx, T, "get_frameCount", null, function (v) { return num(ctx, v, "clock.frameCount"); }),
      unityTime: g(ctx, T, "get_time", null, function (v) { return num(ctx, v, "clock.unityTime", 9); }),
      unscaledTime: g(ctx, T, "get_unscaledTime", null, function (v) { return num(ctx, v, "clock.unscaledTime", 9); }),
      deltaTime: g(ctx, T, "get_deltaTime", null, function (v) { return num(ctx, v, "clock.deltaTime", 9); }),
      timeScale: g(ctx, T, "get_timeScale", null, function (v) { return num(ctx, v, "clock.timeScale"); }),
      realtimeSinceStartup: g(ctx, T, "get_realtimeSinceStartup", null, function (v) { return num(ctx, v, "clock.realtimeSinceStartup", 9); }),
      musicTime: null, musicPlaying: null };
    try {
      var machine = musicMachine(ctx);
      if (machine) {
        var t = fieldAny(machine, ["musicPlayingTime", "<MusicPlayingTime>k__BackingField"]);
        if (t) clock.musicTime = num(ctx, typeof t.value === "number" ? t.value : Number(t.value), "clock.musicTime", 9);
        var playing = fieldAny(machine, ["<IsPlayingMusic>k__BackingField", "isPlayingMusic"]);
        if (playing) clock.musicPlaying = !!playing.value;
        var length = fieldAny(machine, ["<MusicLength>k__BackingField", "musicLength"]);
        if (length) clock.musicLength = num(ctx, Number(length.value), "clock.musicLength", 9);
      }
    } catch (error) { ctx.err("clock.music", error); }
    return clock;
  }
  function readClockEnd(ctx, directors) {
    var T = "UnityEngine.Time", main = directors && directors.main;
    return { directorTime: main ? g(ctx, "UnityEngine.Playables.PlayableDirector", "get_time", main.object, function (v) { return num(ctx, v, "clockEnd.directorTime", 9); }) : null,
      frameCount: g(ctx, T, "get_frameCount", null, function (v) { return num(ctx, v, "clockEnd.frameCount"); }),
      realtimeSinceStartup: g(ctx, T, "get_realtimeSinceStartup", null, function (v) { return num(ctx, v, "clockEnd.realtimeSinceStartup", 9); }) };
  }
  // Scene name through the observer's proven metadata() path; the Screen getters are read here
  // because metadata() turns the ScreenOrientation enum (a bridge ValueType) into NaN.
  function scene(ctx) {
    var m = H.metadata(), S = "UnityEngine.Screen";
    ctx.calls += 5;
    return { name: m.scene, width: g(ctx, S, "get_width", null), height: g(ctx, S, "get_height", null),
      orientation: g(ctx, S, "get_orientation", null, en("ScreenOrientation")), unityVersion: m.unityVersion };
  }
  // Camera census: every active camera with its role and key (cheap; no detail reads).
  function cameraCensus(ctx) {
    if (ctx.memo.cameras) return ctx.memo.cameras;
    var CAM = H.findClass("UnityEngine.Camera", true), list = [];
    var objects = instances(ctx, CAM, 256);
    for (var i = 0; i < objects.length && list.length < CAPS.cameras; i++) {
      var cam = objects[i];
      if (!activeGo(ctx, cam)) continue;
      ctx.objects++;
      var info = pathInfo(ctx, cam);
      list.push({ object: cam, iid: iid(cam), goIid: goIid(ctx, cam), info: info, role: null, key: null, rigDepth: info.segments.lastIndexOf("MainCamera") });
    }
    var roles = {}, sources = {};
    function mark(role, value, source) {
      if (!alive(value)) return;
      var id = goIid(ctx, value);
      if (id !== null && roles[id] === undefined) { roles[id] = role; sources[id] = source; }
    }
    try {
      instances(ctx, cls(ctx, "LiveCoreCameraManager"), 8).slice(0, 2).forEach(function (manager) {
        [["overlay", ["overlayCamera"]], ["cutin", ["cutinCamera"]], ["cutinOverlay", ["cutinOverlayCamera"]]].forEach(function (pair) {
          pair[1].forEach(function (name) {
            var found = fieldAny(manager, backingNames(name));
            if (found) mark(pair[0], found.value, "LiveCoreCameraManager." + found.name);
          });
        });
      });
      instances(ctx, cls(ctx, "LiveSplitScreenEffect"), 4).slice(0, 1).forEach(function (split) {
        layoutOf(split.class).forEach(function (entry) {
          if (!/camera/i.test(entry.name)) return;
          var value = fv(split, entry.name);
          if (value instanceof Il2Cpp.Array) items(value, 4).forEach(function (c, k) { mark("split" + (k + 1), c, "LiveSplitScreenEffect." + entry.name); });
        });
      });
    } catch (error) { ctx.err("cameras.roles", error); }
    var targets = ctx.memo.correctorTargets || {};
    var mains = list.filter(function (c) { return c.rigDepth >= 0 && roles[c.goIid] === undefined; });
    mains.sort(function (a, b) { return (targets[b.iid] ? 1 : 0) - (targets[a.iid] ? 1 : 0) || a.info.segments.length - b.info.segments.length; });
    if (mains.length) { roles[mains[0].goIid] = "main"; sources[mains[0].goIid] = targets[mains[0].iid] ? "MainCamera rig + corrector target" : "MainCamera rig"; }
    var used = {};
    list.forEach(function (c) {
      var role = roles[c.goIid];
      if (role && !used[role]) { c.role = role; c.roleSource = sources[c.goIid]; c.key = "camera:" + role; used[role] = true; }
      else c.key = "camera:path:" + c.info.path;
    });
    list.sort(function (a, b) { return (a.role === "main" ? 0 : 1) - (b.role === "main" ? 0 : 1); });
    ctx.memo.cameras = list;
    return list;
  }
  function cameraKeyByIid(ctx, id) {
    var found = (ctx.memo.cameras || []).filter(function (c) { return c.iid === id; })[0];
    return found ? found.key : null;
  }
  function textureInfo(ctx, texture, path) {
    if (!alive(texture)) return null;
    var out = { name: nameOf(ctx, texture), width: g(ctx, "UnityEngine.Texture", "get_width", texture), height: g(ctx, "UnityEngine.Texture", "get_height", texture) };
    if (isA(texture, H.findClass("UnityEngine.RenderTexture", true))) out.format = g(ctx, "UnityEngine.RenderTexture", "get_format", texture, en("RenderTextureFormat"));
    return out;
  }
  function cameraDetail(ctx, c, index, detailed) {
    var C = "UnityEngine.Camera", cam = c.object, p = "cameras[" + index + "]";
    var out = withPath({ key: c.key, role: c.role }, c.info);
    if (c.roleSource) out.roleSource = c.roleSource;
    out.instanceId = c.iid;
    out.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", cam, bool);
    out.isActiveAndEnabled = g(ctx, "UnityEngine.Behaviour", "get_isActiveAndEnabled", cam, bool);
    out.activeInHierarchy = true;
    out.fieldOfView = g(ctx, C, "get_fieldOfView", cam, function (v) { return num(ctx, v, p + ".fieldOfView", 9); });
    out.aspect = g(ctx, C, "get_aspect", cam, function (v) { return num(ctx, v, p + ".aspect", 9); });
    if (!detailed) { out.summaryOnly = true; return out; }
    out.nearClipPlane = g(ctx, C, "get_nearClipPlane", cam, function (v) { return num(ctx, v, p + ".nearClipPlane", 9); });
    out.farClipPlane = g(ctx, C, "get_farClipPlane", cam, function (v) { return num(ctx, v, p + ".farClipPlane", 9); });
    out.orthographic = g(ctx, C, "get_orthographic", cam, bool);
    out.orthographicSize = g(ctx, C, "get_orthographicSize", cam, function (v) { return num(ctx, v, p + ".orthographicSize", 9); });
    out.usePhysicalProperties = g(ctx, C, "get_usePhysicalProperties", cam, bool);
    out.focalLength = g(ctx, C, "get_focalLength", cam, function (v) { return num(ctx, v, p + ".focalLength", 9); });
    out.lensShift = g(ctx, C, "get_lensShift", cam, function (v) { return raw(ctx, v, 2, p + ".lensShift", 9); });
    out.projection = g(ctx, C, "get_projectionMatrix", cam, function (v) { return raw(ctx, v, 16, p + ".projection", 9); });
    out.worldToCamera = g(ctx, C, "get_worldToCameraMatrix", cam, function (v) { return raw(ctx, v, 16, p + ".worldToCamera", 9); });
    out.rect = g(ctx, C, "get_rect", cam, function (v) { return raw(ctx, v, 4, p + ".rect", 9); });
    out.pixelRect = g(ctx, C, "get_pixelRect", cam, function (v) { return raw(ctx, v, 4, p + ".pixelRect", 9); });
    out.pixelWidth = g(ctx, C, "get_pixelWidth", cam);
    out.pixelHeight = g(ctx, C, "get_pixelHeight", cam);
    out.depth = g(ctx, C, "get_depth", cam, function (v) { return num(ctx, v, p + ".depth", 9); });
    out.clearFlags = g(ctx, C, "get_clearFlags", cam, en("CameraClearFlags"));
    out.backgroundColor = g(ctx, C, "get_backgroundColor", cam, function (v) { return raw(ctx, v, 4, p + ".backgroundColor", 7); });
    out.cullingMask = g(ctx, C, "get_cullingMask", cam);
    out.allowHDR = g(ctx, C, "get_allowHDR", cam, bool);
    out.allowMSAA = g(ctx, C, "get_allowMSAA", cam, bool);
    out.depthTextureMode = g(ctx, C, "get_depthTextureMode", cam, en("DepthTextureMode"));
    out.targetTexture = g(ctx, C, "get_targetTexture", cam, function (v) { return textureInfo(ctx, v, p + ".targetTexture"); });
    var tr = trOf(ctx, cam);
    out.transform = transformOf(ctx, tr, p + ".transform", true);
    if (c.rigDepth >= 0) {
      var rig = tr, up = c.info.segments.length - 1 - c.rigDepth;
      for (var k = 0; k < up && rig; k++) rig = refValue(inv(ctx, "UnityEngine.Transform", "get_parent", rig, []));
      if (rig) {
        var rt = transformOf(ctx, rig, p + ".rig", false);
        out.rig = { path: "/" + c.info.segments.slice(0, c.rigDepth + 1).join("/"), position: rt.position, rotation: rt.rotation, lossyScale: rt.lossyScale };
      }
    }
    return out;
  }
  function correctorObjects(ctx) {
    if (ctx.memo.correctorObjects) return ctx.memo.correctorObjects;
    var out = [], targets = {};
    instances(ctx, cls(ctx, "CameraAspectCorrector"), 64).forEach(function (object) {
      if (out.length >= CAPS.correctors || !activeGo(ctx, object)) return;
      var target = fv(object, "target");
      var id = alive(target) ? iid(target) : null;
      if (id !== null) targets[id] = true;
      out.push({ object: object, target: target, targetIid: id });
    });
    ctx.memo.correctorObjects = out;
    ctx.memo.correctorTargets = targets;
    return out;
  }
  function readCorrectors(ctx) {
    return correctorObjects(ctx).map(function (entry, i) {
      ctx.objects++;
      var object = entry.object, info = pathInfo(ctx, object), p = "correctors[" + i + "]";
      var key = entry.targetIid !== null && cameraKeyByIid(ctx, entry.targetIid) ? "corrector:" + cameraKeyByIid(ctx, entry.targetIid) : "corrector:path:" + info.path;
      var out = withPath({ key: key }, info);
      out.instanceId = iid(object);
      out.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", object, bool);
      out.mode = (function () { var v = numberField(object, ["mode", "<Mode>k__BackingField"]); return v === null ? null : { v: Number(v), n: null }; })();
      out.correction = num(ctx, numberField(object, ["<Correction>k__BackingField", "correction"]), p + ".correction", 9);
      out.defaultOrthographicSize = num(ctx, numberField(object, ["defaultOrthographicSize"]), p + ".defaultOrthographicSize", 9);
      var tinfo = alive(entry.target) ? pathInfo(ctx, entry.target) : null;
      out.target = entry.targetIid === null ? null : { instanceId: entry.targetIid, path: tinfo ? tinfo.path : null, cameraKey: cameraKeyByIid(ctx, entry.targetIid) };
      out.fields = readFields(ctx, object, 1, p + ".fields", ["mode", "<Correction>k__BackingField", "defaultOrthographicSize", "target"]);
      return out;
    });
  }
  function readCameraWork(ctx) {
    var out = [];
    instances(ctx, cls(ctx, "LiveCoreCameraWork"), 32).forEach(function (object) {
      if (out.length >= CAPS.cameraWork || !activeGo(ctx, object)) return;
      ctx.objects++;
      var info = pathInfo(ctx, object), item = withPath({ key: "cameraWork:" + info.path }, info);
      item.class = H.fullType(object);
      item.fields = readFields(ctx, object, 1, "cameraWork[" + out.length + "].fields");
      out.push(item);
    });
    return out;
  }
  function propertyId(ctx, name) {
    if (propertyIds.hasOwnProperty(name)) return propertyIds[name];
    var id = inv(ctx, "UnityEngine.Shader", "PropertyToID", null, [Il2Cpp.string(name)]);
    propertyIds[name] = typeof id === "number" ? id : Number(id);
    return propertyIds[name];
  }
  function readGlobals(ctx, keys) {
    var names = (keys && Array.isArray(keys.globals) && keys.globals.length ? keys.globals : STATIC_GLOBALS).slice(0, CAPS.globals);
    var out = {};
    names.forEach(function (name) {
      if (ctx.pastHard()) { ctx.cut("globals"); return; }
      var id = propertyId(ctx, name);
      out["global:" + name] = { f: g(ctx, "UnityEngine.Shader", "GetGlobalFloat", null, function (v) { return num(ctx, v, "globals." + name + ".f"); }, [id]),
        v: g(ctx, "UnityEngine.Shader", "GetGlobalVector", null, function (v) { return raw(ctx, v, 4, "globals." + name + ".v", 7); }, [id]) };
    });
    if (ctx.arrays && keys && Array.isArray(keys.vectorArrays)) keys.vectorArrays.slice(0, 2).forEach(function (name) {
      var id = propertyId(ctx, name);
      var list = g(ctx, "UnityEngine.Shader", "GetGlobalVectorArray", null, null, [id]);
      var values = items(list, 16);
      out["global:" + name] = { n: values.total, v: values.map(function (v, i) { return raw(ctx, v, 4, "globals." + name + "[" + i + "]", 7); }) };
    });
    return out;
  }
  function directorAssetMembers(ctx) {
    var out = [];
    liveDirectors(ctx).forEach(function (ld) {
      var asset = fv(ld, "asset"), members = asset ? fv(asset, "<Members>k__BackingField") : null;
      if (!(members instanceof Il2Cpp.Array)) return;
      items(members, 12).forEach(function (vo) {
        if (!isObj(vo)) return;
        var suit = fv(vo, "<SuitId>k__BackingField"), suitId = null;
        try { if (suit && fv(suit, "has_value") === true) suitId = Number(fv(suit, "value")); } catch (_) {}
        out.push({ memberId: numberField(vo, ["<MemberMasterId>k__BackingField"]), formationPosition: numberField(vo, ["<FormationPosition>k__BackingField"]), suitId: suitId });
      });
    });
    return out;
  }
  function memberList(ctx) {
    if (ctx.memo.members) return ctx.memo.members;
    var assets = directorAssetMembers(ctx), out = [];
    instances(ctx, cls(ctx, "LiveCoreMember"), 32).forEach(function (object) {
      if (out.length >= CAPS.members || !activeGo(ctx, object)) return;
      var info = pathInfo(ctx, object), memberInfo = fv(object, "memberInfo");
      var formation = memberInfo ? numberField(memberInfo, ["<FormationPosition>k__BackingField"]) : null;
      var match = /\/Members\/Member(\d+)(\/|$)/.exec(info.path || "");
      var slot = match ? Number(match[1]) : formation;
      var found = assets.filter(function (a) { return a.formationPosition === formation && formation !== null; });
      out.push({ object: object, info: info, slot: slot, formationPosition: formation,
        memberId: found.length === 1 ? found[0].memberId : null, suitId: found.length === 1 ? found[0].suitId : null,
        root: match ? "/" + info.segments.slice(0, info.segments.indexOf("Member" + match[1]) + 1).join("/") : info.path });
    });
    out.sort(function (a, b) { return (a.slot || 0) - (b.slot || 0); });
    ctx.memo.members = out;
    return out;
  }
  function readMembersIdentity(ctx) {
    return memberList(ctx).map(function (m) {
      ctx.objects++;
      return withPath({ slot: m.slot, formationPosition: m.formationPosition, memberId: m.memberId, suitId: m.suitId, active: true }, m.info);
    });
  }
  // The prefab root carrying BodyPartManager for each member path prefix.
  function bodyParts(ctx) {
    if (ctx.memo.bodyParts) return ctx.memo.bodyParts;
    var out = [];
    instances(ctx, cls(ctx, "BodyPartManager"), 32).forEach(function (object) {
      if (out.length < CAPS.members && activeGo(ctx, object)) out.push({ object: object, info: pathInfo(ctx, object) });
    });
    ctx.memo.bodyParts = out;
    return out;
  }
  function memberRoot(ctx, member) {
    var prefix = member.root + "/";
    var found = bodyParts(ctx).filter(function (b) { return b.info.path && b.info.path.indexOf(prefix) === 0; })[0];
    if (found) return { tr: trOf(ctx, found.object), info: found.info, manager: found.object, source: "BodyPartManager" };
    var memberTr = trOf(ctx, member.object), model = memberTr ? refValue(inv(ctx, "UnityEngine.Transform", "Find", memberTr, [Il2Cpp.string("Model")])) : null;
    if (model && Number(inv(ctx, "UnityEngine.Transform", "get_childCount", model, [])) > 0) {
      var first = refValue(inv(ctx, "UnityEngine.Transform", "GetChild", model, [0]));
      if (first) return { tr: first, info: pathInfo(ctx, first), manager: null, source: "Model/child0" };
    }
    return null;
  }
  function readAnchors(ctx, keys) {
    var out = [], anchors = (keys && keys.member && keys.member.anchors) || {};
    memberList(ctx).forEach(function (member) {
      if (out.length >= CAPS.anchors || ctx.pastSoft()) return;
      var root = memberRoot(ctx, member);
      if (!root) return;
      ["Hips", "Head", "LeftHand", "RightHand"].forEach(function (name) {
        if (out.length >= CAPS.anchors) return;
        var tr = null, source = null;
        if (root.manager && (name === "Hips" || name === "Head")) {
          var f = fieldAny(root.manager, backingNames(name.toLowerCase()));
          if (f && alive(f.value)) { tr = trOf(ctx, f.value); source = "BodyPartManager." + f.name; }
        }
        if (!tr && anchors[name]) { tr = refValue(inv(ctx, "UnityEngine.Transform", "Find", root.tr, [Il2Cpp.string(anchors[name])])); source = "Find"; }
        if (!tr) return;
        ctx.objects++;
        out.push({ key: "anchor:member" + member.slot + ":" + name, source: source,
          position: g(ctx, "UnityEngine.Transform", "get_position", tr, function (v) { return raw(ctx, v, 3, "anchors." + name, 9); }) });
      });
    });
    if (out.length < CAPS.anchors) {
      var origin = resolvePath(ctx, (keys && keys.stageOrigin) || "/EntryPoint/Live/Stages/MainStage");
      if (origin) out.push({ key: "anchor:stageOrigin", position: g(ctx, "UnityEngine.Transform", "get_position", origin, function (v) { return raw(ctx, v, 3, "anchors.stageOrigin", 9); }) });
    }
    return out;
  }
  function readRenderSettings(ctx) {
    var R = "UnityEngine.RenderSettings";
    function c4(path) { return function (v) { return raw(ctx, v, 4, "renderSettings." + path, 7); }; }
    function f(path) { return function (v) { return num(ctx, v, "renderSettings." + path); }; }
    var skybox = g(ctx, R, "get_skybox", null);
    return { fog: g(ctx, R, "get_fog", null, bool), fogMode: g(ctx, R, "get_fogMode", null, en("FogMode")),
      fogColor: g(ctx, R, "get_fogColor", null, c4("fogColor")), fogDensity: g(ctx, R, "get_fogDensity", null, f("fogDensity")),
      fogStartDistance: g(ctx, R, "get_fogStartDistance", null, f("fogStartDistance")),
      fogEndDistance: g(ctx, R, "get_fogEndDistance", null, f("fogEndDistance")),
      ambientMode: g(ctx, R, "get_ambientMode", null, en("AmbientMode")),
      ambientSkyColor: g(ctx, R, "get_ambientSkyColor", null, c4("ambientSkyColor")),
      ambientEquatorColor: g(ctx, R, "get_ambientEquatorColor", null, c4("ambientEquatorColor")),
      ambientGroundColor: g(ctx, R, "get_ambientGroundColor", null, c4("ambientGroundColor")),
      ambientIntensity: g(ctx, R, "get_ambientIntensity", null, f("ambientIntensity")),
      ambientLight: g(ctx, R, "get_ambientLight", null, c4("ambientLight")),
      reflectionIntensity: g(ctx, R, "get_reflectionIntensity", null, f("reflectionIntensity")),
      skybox: alive(skybox) ? nameOf(ctx, skybox) : null };
  }
  function readLights(ctx) {
    var L = "UnityEngine.Light", out = [];
    instances(ctx, H.findClass(L, true), 256).forEach(function (light) {
      if (out.length >= CAPS.lights || ctx.pastHard() || !activeGo(ctx, light)) return;
      ctx.objects++;
      var p = "lights[" + out.length + "]", info = pathInfo(ctx, light), tr = trOf(ctx, light);
      var item = withPath({ key: "light:" + info.path }, info);
      item.type = g(ctx, L, "get_type", light, en("LightType"));
      item.color = g(ctx, L, "get_color", light, function (v) { return raw(ctx, v, 4, p + ".color", 7); });
      item.intensity = g(ctx, L, "get_intensity", light, function (v) { return num(ctx, v, p + ".intensity"); });
      item.range = g(ctx, L, "get_range", light, function (v) { return num(ctx, v, p + ".range"); });
      item.spotAngle = g(ctx, L, "get_spotAngle", light, function (v) { return num(ctx, v, p + ".spotAngle"); });
      item.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", light, bool);
      item.shadows = g(ctx, L, "get_shadows", light, en("LightShadows"));
      item.cullingMask = g(ctx, L, "get_cullingMask", light);
      var t = transformOf(ctx, tr, p, false);
      item.position = t.position; item.rotation = t.rotation;
      out.push(item);
    });
    return out;
  }

  // ------------------------------------------------------------------ record runner
  function section(ctx, record, name, fn, mode) {
    if (mode !== "always" && (ctx.pastHard() || (mode === "optional" && ctx.pastSoft()))) { ctx.cut(name); return; }
    try {
      var value = fn();
      if (value !== undefined) record[name] = value;
    } catch (error) { ctx.err(name, error); record[name] = null; }
  }
  function finish(ctx, record) {
    record.cost = ctx.cost();
    record.nonFinite = ctx.nonFinite;
    if (ctx.errors.length) record.errors = ctx.errors;
    return record;
  }
  function frame(options) {
    var ctx = new Ctx("frame", options), record = { kind: "frame" }, keys = options.keys || {}, directors = null;
    section(ctx, record, "directors", function () { directors = readDirectors(ctx); return directors.list; }, "always");
    section(ctx, record, "clock", function () { return readClock(ctx, directors); }, "always");
    section(ctx, record, "scene", function () { return scene(ctx); }, "always");
    // The camera census, the correctors and the cameras are read in every frame whatever the
    // budget says (bounded by CAPS.cameras / CAPS.correctors): the main camera's FoV, projection
    // and corrector are the values the comparison exists for. Past the soft budget only the
    // cameras after index 0 degrade, to summary-only (key, role, enabled, fieldOfView, aspect).
    section(ctx, record, "cameraCensus", function () { correctorObjects(ctx); cameraCensus(ctx); return undefined; }, "always");
    section(ctx, record, "correctors", function () { return readCorrectors(ctx); }, "always");
    section(ctx, record, "cameras", function () {
      var out = [];
      (ctx.memo.cameras || []).forEach(function (c, i) {
        var detailed = i === 0 || (i < CAPS.camerasDetailed && !ctx.pastSoft());
        if (!detailed && i < CAPS.camerasDetailed) ctx.cut("cameras.detail");
        ctx.objects++;
        out.push(cameraDetail(ctx, c, i, detailed));
      });
      return out;
    }, "always");
    section(ctx, record, "cameraWork", function () { return readCameraWork(ctx); }, "required");
    section(ctx, record, "globals", function () { return readGlobals(ctx, keys); }, "required");
    section(ctx, record, "members", function () { return readMembersIdentity(ctx); }, "required");
    section(ctx, record, "anchors", function () { return readAnchors(ctx, keys); }, "optional");
    section(ctx, record, "renderSettings", function () { return readRenderSettings(ctx); }, "optional");
    section(ctx, record, "lights", function () { return readLights(ctx); }, "optional");
    section(ctx, record, "clockEnd", function () { return readClockEnd(ctx, directors); }, "always");
    return finish(ctx, record);
  }

  // ------------------------------------------------------------------ full parts
  function cursorOf(options) { return options.cursor && typeof options.cursor === "object" ? options.cursor : {}; }
  function childCount(ctx, tr) { var n = inv(ctx, "UnityEngine.Transform", "get_childCount", tr, []); return typeof n === "number" ? n : 0; }
  function childAt(ctx, tr, index) {
    if (index < 0 || index >= childCount(ctx, tr)) return null;
    return refValue(inv(ctx, "UnityEngine.Transform", "GetChild", tr, [index]));
  }
  // Pre-order walk of a Transform subtree, resumable from a child-index path (plain JSON).
  function walk(ctx, root, start, maxDepth, limit, visit) {
    var stack = [], node = root, path = [], names = [nameOf(ctx, root)], emitted = 0, cur;
    start = Array.isArray(start) ? start : [];
    for (var k = 0; k < start.length; k++) {
      var count = childCount(ctx, node), index = Number(start[k]);
      stack.push({ tr: node, path: path, names: names, count: count, next: index + 1 });
      if (!(index >= 0 && index < count)) { stack[stack.length - 1].next = count; node = null; break; }
      node = childAt(ctx, node, index);
      if (!node) { node = null; break; }
      path = path.concat([index]); names = names.concat([nameOf(ctx, node)]);
    }
    cur = node ? { tr: node, path: path, names: names } : null;
    for (;;) {
      if (cur) {
        if (emitted >= limit || (emitted > 0 && ctx.pastSoft())) return { next: cur.path, emitted: emitted };
        ctx.objects++;
        var count2 = visit(cur.tr, cur.path, cur.names);
        emitted++;
        if (cur.path.length < maxDepth && count2 > 0) stack.push({ tr: cur.tr, path: cur.path, names: cur.names, count: count2, next: 0 });
        cur = null;
      }
      while (stack.length) {
        var top = stack[stack.length - 1];
        if (top.next < top.count) {
          var i = top.next++, child = childAt(ctx, top.tr, i);
          if (child) { cur = { tr: child, path: top.path.concat([i]), names: top.names.concat([nameOf(ctx, child)]) }; break; }
        } else stack.pop();
      }
      if (!cur) return { next: null, emitted: emitted };
    }
  }
  function partCensus(ctx, options) {
    var cursor = cursorOf(options), done = Number(cursor.emitted) || 0;
    var root = resolvePath(ctx, options.root || "/EntryPoint");
    if (!root) return { census: { roots: [], nodes: [] }, next: null };
    var COMP = H.findClass("UnityEngine.Component", true), nodes = [];
    var result = walk(ctx, root, cursor.path, CAPS.censusDepth, Math.min(CAPS.censusChunk, CAPS.censusNodes - done), function (tr, path, names) {
      var go = inv(ctx, "UnityEngine.Component", "get_gameObject", tr, []), count = childCount(ctx, tr);
      var node = { path: "/" + names.map(stripName).join("/"), index: path.length ? path[path.length - 1] : 0, depth: path.length,
        activeSelf: g(ctx, "UnityEngine.GameObject", "get_activeSelf", go, bool),
        activeInHierarchy: g(ctx, "UnityEngine.GameObject", "get_activeInHierarchy", go, bool), childCount: count, components: [] };
      var rawPath = "/" + names.join("/");
      if (rawPath !== node.path) node.rawPath = rawPath;
      try {
        items(inv(ctx, "UnityEngine.Component", "GetComponents", tr, [COMP.type.object]), CAPS.components).forEach(function (component) {
          node.components.push(isObj(component) ? H.fullType(component) : null);
        });
      } catch (error) { ctx.err("census.components", error); }
      nodes.push(node);
      return count;
    });
    var total = done + result.emitted;
    return { census: { roots: [options.root || "/EntryPoint"], nodes: nodes },
      next: result.next && total < CAPS.censusNodes ? { path: result.next, emitted: total } : null };
  }
  function partQuality(ctx) {
    var holders = ["LiveDirector", "LiveDirectorBase", "LiveCoreCameraManager", "LiveCoreStageManager", "LiveCoreMemberManager", "LiveMvScene"];
    var out = { holder: null, values: null, unity: {} };
    for (var i = 0; i < holders.length && !out.values; i++) {
      var klass = cls(ctx, holders[i]);
      if (!klass || !unityObjectClass(klass)) continue;
      var objects = instances(ctx, klass, 16);
      for (var j = 0; j < objects.length && !out.values; j++) {
        var found = fieldAny(objects[j], ["liveQualitySetting", "<LiveQualitySetting>k__BackingField", "qualitySetting"]);
        if (!found || !isObj(found.value)) continue;
        ctx.objects++;
        out.holder = klassName(klass) + "." + found.name;
        out.voClass = H.fullType(found.value);
        out.values = {};
        layoutOf(found.value.class).forEach(function (entry) {
          var m = /^<(.+)>k__BackingField$/.exec(entry.name), name = m ? m[1] : entry.name;
          var value = fv(found.value, entry.name), conv = convert(ctx, value, entry.name, 2, "quality." + name, entry.typeName);
          out.values[name] = conv.t === "enum" ? conv.v : PRIMITIVE[entry.typeName] || conv.t === "int" || conv.t === "f32" ? conv.v : conv;
        });
      }
    }
    var Q = "UnityEngine.QualitySettings";
    out.unity.activeColorSpace = g(ctx, Q, "get_activeColorSpace", null, en("ColorSpace"));
    out.unity.vSyncCount = g(ctx, Q, "get_vSyncCount", null);
    out.unity.antiAliasing = g(ctx, Q, "get_antiAliasing", null);
    out.unity.targetFrameRate = g(ctx, "UnityEngine.Application", "get_targetFrameRate", null);
    return { quality: out, next: null };
  }
  function sortedActive(ctx, klass, cursor, cap, total, emitBudget, visit) {
    var after = typeof cursor.afterInstanceId === "number" ? cursor.afterInstanceId : null, done = Number(cursor.emitted) || 0;
    var list = instances(ctx, klass, CAPS.enumerate).map(function (o) { return { o: o, id: iid(o) }; })
      .filter(function (e) { return after === null || e.id > after; });
    list.sort(function (a, b) { return a.id - b.id; });
    var out = [], last = after, i;
    for (i = 0; i < list.length; i++) {
      if (out.length >= cap || done + out.length >= total) break;
      if (i > 0 && ctx.pastSoft()) { ctx.cut("objects"); break; }
      last = list[i].id;
      ctx.objects++;
      if (!activeGo(ctx, list[i].o)) continue;
      try { out.push(visit(list[i].o, list[i].id, out.length)); } catch (error) { ctx.err("object:" + list[i].id, error); }
    }
    var exhausted = i >= list.length || done + out.length >= total;
    return { list: out, next: exhausted ? null : { afterInstanceId: last, emitted: done + out.length } };
  }
  function scopeOf(path) {
    var m = /^\/EntryPoint\/Live\/Members\/Member(\d+)(\/|$)/.exec(path || "");
    if (m) return "member" + m[1];
    if (/^\/EntryPoint\/Live\/Stages\/[^/]+\/Effect(\/|$)/.test(path || "")) return "effect";
    if (/^\/EntryPoint\/Live\/Stages\//.test(path || "")) return "stage";
    return "other";
  }
  function materialSummary(ctx, material) {
    var id = iid(material), memo = ctx.memo.materials || (ctx.memo.materials = {});
    if (memo[id]) return memo[id];
    var shader = g(ctx, "UnityEngine.Material", "get_shader", material);
    var keywords = g(ctx, "UnityEngine.Material", "get_shaderKeywords", material, function (v) { return items(v, CAPS.keywords).map(str); });
    memo[id] = { instanceId: id, name: nameOf(ctx, material), shader: alive(shader) ? nameOf(ctx, shader) : null,
      renderQueue: g(ctx, "UnityEngine.Material", "get_renderQueue", material), keywords: keywords || [] };
    return memo[id];
  }
  function partRenderers(ctx, options) {
    var R = "UnityEngine.Renderer", SMR = H.findClass("UnityEngine.SkinnedMeshRenderer", true), MF = H.findClass("UnityEngine.MeshFilter", true);
    var result = sortedActive(ctx, H.findClass(R, true), cursorOf(options), CAPS.rendererChunk, CAPS.renderers, null, function (r, id, n) {
      var p = "renderers[" + n + "]", info = pathInfo(ctx, r), tr = trOf(ctx, r);
      var item = withPath({ key: "renderer:" + info.path }, info);
      item.scope = scopeOf(info.path); item.class = H.fullType(r); item.instanceId = id;
      var mesh = null;
      if (isA(r, SMR)) mesh = g(ctx, "UnityEngine.SkinnedMeshRenderer", "get_sharedMesh", r);
      else if (MF) { var filter = g(ctx, "UnityEngine.Component", "GetComponent", r, null, [MF.type.object]); if (alive(filter)) mesh = g(ctx, "UnityEngine.MeshFilter", "get_sharedMesh", filter); }
      item.mesh = alive(mesh) ? nameOf(ctx, mesh) : null;
      item.enabled = g(ctx, R, "get_enabled", r, bool);
      // The GameObject layer: the comparator tests it against the main camera's cullingMask
      // (members hidden by a culler clip stay enabled and active on the Invisible layer).
      var go = refValue(g(ctx, "UnityEngine.Component", "get_gameObject", r));
      item.layer = go ? g(ctx, "UnityEngine.GameObject", "get_layer", go, enumInt) : null;
      item.isVisible = g(ctx, R, "get_isVisible", r, bool);
      item.activeInHierarchy = true;
      item.bounds = g(ctx, R, "get_bounds", r, function (v) { var b = raw(ctx, v, 6, p + ".bounds", 9); return b ? { center: b.slice(0, 3), extents: b.slice(3) } : null; });
      item.transform = transformOf(ctx, tr, p + ".transform", false);
      item.lightmapIndex = g(ctx, R, "get_lightmapIndex", r);
      item.lightmapScaleOffset = g(ctx, R, "get_lightmapScaleOffset", r, function (v) { return raw(ctx, v, 4, p + ".lightmapScaleOffset", 9); });
      item.sortingOrder = g(ctx, R, "get_sortingOrder", r);
      item.materials = [];
      var shared = g(ctx, R, "get_sharedMaterials", r, function (v) { return items(v, CAPS.slots); }) || [];
      shared.forEach(function (material, slot) {
        if (!alive(material)) { item.materials.push({ slot: slot, instanceId: null }); return; }
        var s = materialSummary(ctx, material);
        item.materials.push({ slot: slot, instanceId: s.instanceId, name: s.name, shader: s.shader, renderQueue: s.renderQueue, keywords: s.keywords });
      });
      if (shared.total > shared.length) item.materialsTotal = shared.total;
      return item;
    });
    return { renderers: result.list, next: result.next };
  }
  var DEFAULT_PROPS = { _MainTex: "tex", _TintColor: "color", _AmbientColor: "color", _BlendColor: "color", _Color: "color",
    _EmissiveColor: "color", _EmissiveIntensity: "float", _Cutoff: "float", _MainTexMipmapBias: "float", _RimlightColor: "color",
    _RimlightDirection: "vector", _RimglightIntensity: "float", _RimglightPower: "float" };
  function materialProps(shaders, shaderName) {
    if (shaders && shaders[shaderName]) return { props: shaders[shaderName], source: "keys" };
    var union = {};
    Object.keys(DEFAULT_PROPS).forEach(function (k) { union[k] = DEFAULT_PROPS[k]; });
    return { props: union, source: "default" };
  }
  // A wanted material through the renderer slot that uses it (options.materials[i].resolve =
  // [{path, slot, rendererId}] from the renderers part): GameObject.Find + Transform.Find,
  // GetComponent(Renderer), get_sharedMaterials()[slot], renderer and material instance ids checked.
  function materialViaRenderer(ctx, w, R) {
    var list = Array.isArray(w.resolve) ? w.resolve.slice(0, 2) : [];
    for (var k = 0; k < list.length; k++) {
      var ref = list[k] || {};
      if (typeof ref.path !== "string" || typeof ref.slot !== "number" || ref.slot < 0 || ref.slot >= CAPS.slots) continue;
      var tr = resolvePath(ctx, ref.path);
      if (!tr) continue;
      var renderer = refValue(g(ctx, "UnityEngine.Component", "GetComponent", tr, null, [R.type.object]));
      if (!alive(renderer) || (typeof ref.rendererId === "number" && iid(renderer) !== ref.rendererId)) continue;
      var shared = g(ctx, "UnityEngine.Renderer", "get_sharedMaterials", renderer, function (v) { return items(v, CAPS.slots); }) || [];
      var material = ref.slot < shared.length ? shared[ref.slot] : null;
      if (alive(material) && iid(material) === w.instanceId) return material;
    }
    return null;
  }
  function partMaterials(ctx, options) {
    var wanted = Array.isArray(options.materials) ? options.materials.slice(0, CAPS.materialChunk) : [];
    var M = "UnityEngine.Material", R = H.findClass("UnityEngine.Renderer", true), scanned = null;
    // Fallback only, at most once per chunk: one FindObjectsOfTypeAll(Material) for the wanted
    // materials that no renderer slot resolved (renderer gone, renamed or inactive since).
    function scan() {
      if (scanned) return scanned;
      var ids = {};
      scanned = {};
      wanted.forEach(function (w) { ids[w.instanceId] = true; });
      instances(ctx, H.findClass(M, true), CAPS.enumerate).forEach(function (o) { var id = iid(o); if (ids[id]) scanned[id] = o; });
      return scanned;
    }
    var out = [], processed = 0, resolution = { renderer: 0, scan: 0, missing: 0 };
    for (var i = 0; i < wanted.length; i++) {
      if (i > 0 && ctx.pastSoft()) { ctx.cut("materials"); break; }
      var w = wanted[i], material = null, via = "renderer";
      ctx.objects++;
      try { material = R ? materialViaRenderer(ctx, w, R) : null; } catch (error) { ctx.err("materials.resolve", error); material = null; }
      if (!material) { via = "scan"; material = scan()[w.instanceId] || null; }
      if (!alive(material)) {
        resolution.missing++; processed++;
        out.push({ instanceId: w.instanceId, usedBy: w.usedBy || [], missingObject: true });
        continue;
      }
      var s = materialSummary(ctx, material), spec = materialProps(options.shaders, s.shader);
      var item = { instanceId: w.instanceId, name: s.name, shader: s.shader, usedBy: w.usedBy || [], resolvedBy: via, propertySource: spec.source, properties: {}, missing: [] };
      var names = Object.keys(spec.props).slice(0, CAPS.properties), complete = true;
      for (var j = 0; j < names.length; j++) {
        // The first material of a chunk always completes (progress is guaranteed); a later one
        // that crosses the hard budget is dropped here and retried first in the next chunk.
        if (i > 0 && ctx.pastHard()) { ctx.cut("materials.properties"); complete = false; break; }
        var name = names[j], type = spec.props[name], id = propertyId(ctx, name), p = "materials." + s.name + "." + name;
        if (!g(ctx, M, "HasProperty", material, bool, [id])) { item.missing.push(name); continue; }
        if (type === "color") item.properties[name] = { t: "color", v: g(ctx, M, "GetColor", material, function (v) { return raw(ctx, v, 4, p, 7); }, [id]) };
        else if (type === "vector") item.properties[name] = { t: "vector", v: g(ctx, M, "GetVector", material, function (v) { return raw(ctx, v, 4, p, 7); }, [id]) };
        else if (type === "tex") {
          var tex = g(ctx, M, "GetTexture", material, null, [id]);
          var scale = g(ctx, M, "GetTextureScale", material, function (v) { return raw(ctx, v, 2, p + ".scale", 7); }, [id]);
          var offset = g(ctx, M, "GetTextureOffset", material, function (v) { return raw(ctx, v, 2, p + ".offset", 7); }, [id]);
          item.properties[name] = { t: "tex", v: alive(tex) ? textureInfo(ctx, tex, p) : null, st: scale && offset ? scale.concat(offset) : null };
        } else item.properties[name] = { t: "float", v: g(ctx, M, "GetFloat", material, function (v) { return num(ctx, v, p); }, [id]) };
      }
      if (!complete) break;
      resolution[via]++; processed++;
      out.push(item);
    }
    return { materials: out, processed: processed, resolution: resolution, next: null };
  }
  function materialIdsOf(value) {
    var out = [];
    function add(v) { if (isObj(v) && unityObjectClass(v.class) && /Material$/.test(v.class.name)) out.push(iid(v)); }
    if (value instanceof Il2Cpp.Array) items(value, 64).forEach(add);
    else if (value instanceof Il2Cpp.Object && isObj(value)) {
      var name = klassName(value.class) || "";
      if (/List`1/.test(name)) { var backing = fv(value, "_items"), size = Number(fv(value, "_size")) || 0; if (backing instanceof Il2Cpp.Array) items(backing, Math.min(size, 64)).forEach(add); }
      else add(value);
    }
    return out;
  }
  function partLightingRefs(ctx, options) {
    var classes = (options.keys && Array.isArray(options.keys.lightingClasses) ? options.keys.lightingClasses : DEFAULT_LIGHTING).slice(0, 16);
    var out = [];
    classes.forEach(function (key) {
      if (ctx.pastHard()) { ctx.cut("lightingRefs"); return; }
      var klass = cls(ctx, key);
      instances(ctx, klass, 64).slice(0, CAPS.lightingPerClass).forEach(function (object) {
        if (!activeGo(ctx, object)) return;
        ctx.objects++;
        var info = pathInfo(ctx, object);
        layoutOf(object.class).forEach(function (entry) {
          if (!/Material/.test(entry.typeName || "")) return;
          var ids = materialIdsOf(fv(object, entry.name));
          out.push({ componentKey: "component:" + info.path + "#" + object.class.name, class: H.fullType(object), field: entry.name, materials: ids });
        });
      });
    });
    return { lightingRefs: out, next: null };
  }
  function partMembers(ctx, options) {
    var cursor = cursorOf(options), index = Number(cursor.index) || 0, list = memberList(ctx), keys = options.keys || {};
    var member = list[index];
    if (!member) return { members: [], next: null };
    ctx.objects++;
    var out = withPath({ slot: member.slot, formationPosition: member.formationPosition, memberId: member.memberId, suitId: member.suitId }, member.info);
    var root = memberRoot(ctx, member);
    out.rootPath = root ? root.info.path : null;
    out.rootSource = root ? root.source : null;
    var memberTr = trOf(ctx, member.object), model = memberTr ? refValue(inv(ctx, "UnityEngine.Transform", "Find", memberTr, [Il2Cpp.string("Model")])) : null;
    out.modelLocalScale = model ? g(ctx, "UnityEngine.Transform", "get_localScale", model, function (v) { return raw(ctx, v, 3, "members.modelLocalScale", 9); }) : null;
    var scaling = instances(ctx, cls(ctx, "LiveCoreMemberNodeScaling"), 32).filter(function (o) { var p = pathInfo(ctx, o).path; return p && p.indexOf(member.root) === 0; })[0];
    out.nodeScaling = scaling ? readFields(ctx, scaling, 1, "members.nodeScaling") : null;
    out.bones = [];
    var bones = (keys.member && Array.isArray(keys.member.bones) ? keys.member.bones : []).slice(0, CAPS.bonesPerMember);
    for (var i = 0; root && i < bones.length; i++) {
      if (i > 0 && ctx.pastHard()) { ctx.cut("members.bones"); break; }
      var bone = refValue(inv(ctx, "UnityEngine.Transform", "Find", root.tr, [Il2Cpp.string(bones[i])]));
      if (!bone) { out.bones.push({ key: "member:" + member.slot + ":" + bones[i], missing: true }); continue; }
      ctx.objects++;
      var t = transformOf(ctx, bone, "members.bones[" + i + "]", true);
      out.bones.push({ key: "member:" + member.slot + ":" + bones[i], path: root.info.path + "/" + bones[i], position: t.position,
        rotation: t.rotation, lossyScale: t.lossyScale, localPosition: t.localPosition, localRotation: t.localRotation });
    }
    out.blendShapes = [];
    var SMR = "UnityEngine.SkinnedMeshRenderer", recorded = 0;
    instances(ctx, H.findClass(SMR, true), 1024).forEach(function (r) {
      if (ctx.pastSoft() || recorded >= CAPS.blendShapes) return;
      var info = pathInfo(ctx, r);
      if (!info.path || info.path.indexOf(member.root + "/") !== 0 || !activeGo(ctx, r)) return;
      var mesh = g(ctx, SMR, "get_sharedMesh", r);
      if (!alive(mesh)) return;
      var count = Number(g(ctx, "UnityEngine.Mesh", "get_blendShapeCount", mesh)) || 0, weights = {};
      for (var k = 0; k < count && k < CAPS.blendShapesInspected && recorded < CAPS.blendShapes; k++) {
        if (ctx.pastHard()) { ctx.cut("members.blendShapes"); break; }
        var w = g(ctx, SMR, "GetBlendShapeWeight", r, function (v) { return num(ctx, v, "blendShape"); }, [k]);
        if (w) { weights[g(ctx, "UnityEngine.Mesh", "GetBlendShapeName", mesh, str, [k]) || String(k)] = w; recorded++; }
      }
      out.blendShapes.push({ rendererKey: "renderer:" + info.path, count: count, weights: weights });
    });
    return { members: [out], next: index + 1 < list.length ? { index: index + 1 } : null };
  }
  function springManagers(ctx) {
    var klass = cls(ctx, "SwingBoneManager"), out = [];
    if (klass && unityObjectClass(klass)) {
      instances(ctx, klass, 64).forEach(function (m) { if (activeGo(ctx, m)) out.push({ object: m, id: iid(m), source: "FindObjectsOfTypeAll" }); });
      out.sort(function (a, b) { return a.id - b.id; });
      return out;
    }
    instances(ctx, cls(ctx, "LiveCoreMemberManager"), 4).forEach(function (manager) {
      var found = fieldAny(manager, ["swingBoneManagers", "<SwingBoneManagers>k__BackingField"]);
      if (!found) return;
      var list = found.value instanceof Il2Cpp.Array ? items(found.value, 16) : [];
      if (!list.length && isObj(found.value)) { var backing = fv(found.value, "_items"), size = Number(fv(found.value, "_size")) || 0; if (backing instanceof Il2Cpp.Array) list = items(backing, Math.min(16, size)); }
      list.forEach(function (m, i) { if (isObj(m)) out.push({ object: m, id: i, source: "LiveCoreMemberManager." + found.name + "[" + i + "]" }); });
    });
    return out;
  }
  function partSprings(ctx, options) {
    var cursor = cursorOf(options), index = Number(cursor.index) || 0, managers = springManagers(ctx), entry = managers[index];
    if (!entry) return { springs: [], next: null };
    ctx.objects++;
    var manager = entry.object, isUnity = unityObjectClass(manager.class), info = isUnity ? pathInfo(ctx, manager) : { path: null, rawPath: null };
    var out = { managerKey: "spring:" + (info.path || entry.source), class: H.fullType(manager), source: entry.source, bones: [] };
    if (info.path) out.path = info.path;
    var boneField = null;
    layoutOf(manager.class).forEach(function (f) { if (!boneField && /SwingBone(\[\]|>)/.test(f.typeName || "") && !/Manager/.test(f.typeName)) boneField = f.name; });
    out.fields = readFields(ctx, manager, 1, "springs.fields", boneField ? [boneField] : null);
    if (boneField) {
      var value = fv(manager, boneField), bones = value instanceof Il2Cpp.Array ? items(value, CAPS.swingBones) : [];
      if (!bones.length && isObj(value)) { var backing = fv(value, "_items"), size = Number(fv(value, "_size")) || 0; if (backing instanceof Il2Cpp.Array) bones = items(backing, Math.min(CAPS.swingBones, size)); }
      out.boneField = boneField; out.boneCount = bones.total !== undefined ? bones.total : bones.length;
      for (var i = 0; i < bones.length; i++) {
        if (i > 0 && ctx.pastSoft()) { ctx.cut("springs.bones"); out.incomplete = true; break; }
        var bone = bones[i];
        if (!isObj(bone)) continue;
        ctx.objects++;
        var item = { index: i, class: H.fullType(bone) };
        if (unityObjectClass(bone.class) && alive(bone)) {
          var binfo = pathInfo(ctx, bone), tr = trOf(ctx, bone);
          item.key = "spring:" + binfo.path; item.path = binfo.path;
          item.localRotation = g(ctx, "UnityEngine.Transform", "get_localRotation", tr, function (v) { return raw(ctx, v, 4, "springs.localRotation", 9); });
        }
        var fields = readFields(ctx, bone, CAPS.fieldDepth, "springs.bone"), compact = {}, n = 0;
        Object.keys(fields || {}).forEach(function (k) { if (n < 12 && /tip|rot|position|angle|length|velocity|weight/i.test(k)) { compact[k] = fields[k]; n++; } });
        item.fields = compact;
        out.bones.push(item);
      }
    }
    return { springs: [out], next: index + 1 < managers.length ? { index: index + 1 } : null };
  }
  function partStageNodes(ctx, options) {
    var cursor = cursorOf(options), bindings = (options.keys && Array.isArray(options.keys.bindings) ? options.keys.bindings : []);
    var b = Number(cursor.binding) || 0, done = Number(cursor.emitted) || 0, out = [];
    while (b < bindings.length && done + out.length < CAPS.stageNodes) {
      var binding = bindings[b], root = resolvePath(ctx, binding);
      if (!root) { out.push({ binding: binding, relPath: "", missing: true }); b++; cursor = {}; if (ctx.pastSoft()) break; continue; }
      var limit = Math.min(CAPS.stageChunk - out.length, CAPS.stageNodes - done - out.length);
      if (limit <= 0) break;
      var result = walk(ctx, root, cursor.path, CAPS.stageDepth, limit, function (tr, path, names) {
        var go = inv(ctx, "UnityEngine.Component", "get_gameObject", tr, []), t = transformOf(ctx, tr, "stageNodes[" + out.length + "]", false);
        var rel = names.slice(1).map(stripName).join("/");
        out.push({ binding: binding, relPath: rel, path: binding + (rel ? "/" + rel : ""),
          activeSelf: g(ctx, "UnityEngine.GameObject", "get_activeSelf", go, bool),
          activeInHierarchy: g(ctx, "UnityEngine.GameObject", "get_activeInHierarchy", go, bool),
          position: t.position, rotation: t.rotation, lossyScale: t.lossyScale });
        return childCount(ctx, tr);
      });
      if (result.next) return { stageNodes: out, next: { binding: b, path: result.next, emitted: done + out.length } };
      b++; cursor = {};
      if (out.length >= CAPS.stageChunk || ctx.pastSoft()) break;
    }
    var more = b < bindings.length && done + out.length < CAPS.stageNodes;
    return { stageNodes: out, next: more ? { binding: b, path: [], emitted: done + out.length } : null };
  }
  function partParticles(ctx, options) {
    var P = "UnityEngine.ParticleSystem", PSR = H.findClass("UnityEngine.ParticleSystemRenderer", true);
    var result = sortedActive(ctx, H.findClass(P, true), cursorOf(options), CAPS.particleChunk, CAPS.particles, null, function (ps, id, n) {
      var p = "particles[" + n + "]", info = pathInfo(ctx, ps), item = withPath({ key: "particles:" + info.path }, info);
      item.instanceId = id;
      item.isPlaying = g(ctx, P, "get_isPlaying", ps, bool);
      item.isEmitting = g(ctx, P, "get_isEmitting", ps, bool);
      item.isPaused = g(ctx, P, "get_isPaused", ps, bool);
      item.particleCount = g(ctx, P, "get_particleCount", ps);
      item.time = g(ctx, P, "get_time", ps, function (v) { return num(ctx, v, p + ".time", 9); });
      item.randomSeed = g(ctx, P, "get_randomSeed", ps, function (v) { return num(ctx, v, p + ".randomSeed", 15); });
      item.useAutoRandomSeed = g(ctx, P, "get_useAutoRandomSeed", ps, bool);
      var renderer = PSR ? g(ctx, "UnityEngine.Component", "GetComponent", ps, null, [PSR.type.object]) : null;
      item.rendererEnabled = alive(renderer) ? g(ctx, "UnityEngine.Renderer", "get_enabled", renderer, bool) : null;
      return item;
    });
    return { particles: result.list, next: result.next };
  }
  function partPost(ctx) {
    var out = { holders: [], enablePostEffect: null }, seen = {};
    function add(object, source) {
      var id = iid(object);
      if (seen[id] || out.holders.length >= CAPS.holders || ctx.pastHard()) return;
      seen[id] = true;
      ctx.objects++;
      var info = pathInfo(ctx, object), item = withPath({ key: "post:" + info.path + "#" + object.class.name, class: H.fullType(object), source: source }, info);
      item.enabled = g(ctx, "UnityEngine.Behaviour", "get_enabled", object, bool);
      item.fields = readFields(ctx, object, 0, "post.fields");
      if (item.fields && item.fields.enablePostEffect && out.enablePostEffect === null) out.enablePostEffect = item.fields.enablePostEffect.v;
      out.holders.push(item);
    }
    instances(ctx, cls(ctx, "LiveCoreCamera"), 16).forEach(function (o) { if (activeGo(ctx, o)) add(o, "LiveCoreCamera"); });
    var COMP = H.findClass("UnityEngine.Component", true);
    cameraCensus(ctx).slice(0, CAPS.camerasDetailed).forEach(function (c) {
      if (ctx.pastSoft()) return;
      items(g(ctx, "UnityEngine.Component", "GetComponents", c.object, null, [COMP.type.object]), 24).forEach(function (component) {
        if (isObj(component) && POST_CLASS.test(component.class.name) && alive(component)) add(component, "camera:" + c.key);
      });
    });
    return { post: out, next: null };
  }
  function sample(options) {
    var part = String(options.part || "frame");
    if (PARTS.indexOf(part) < 0) throw new Error("MVDUMP_UNKNOWN_PART:" + part);
    if (part === "frame") return frame(options);
    var ctx = new Ctx("full", options), record = { kind: "full", part: part, cursor: cursorOf(options) }, directors = null;
    section(ctx, record, "directors", function () { directors = readDirectors(ctx); return undefined; }, "always");
    section(ctx, record, "clock", function () { return readClock(ctx, directors); }, "always");
    var body = null;
    try {
      if (part === "census") body = partCensus(ctx, options);
      else if (part === "quality") body = partQuality(ctx, options);
      else if (part === "fovmodNative") body = { fovmodNative: H.nativeFeatureState(), next: null };
      else if (part === "renderers") body = partRenderers(ctx, options);
      else if (part === "materials") body = partMaterials(ctx, options);
      else if (part === "lightingRefs") body = partLightingRefs(ctx, options);
      else if (part === "members") body = partMembers(ctx, options);
      else if (part === "springs") body = partSprings(ctx, options);
      else if (part === "stageNodes") body = partStageNodes(ctx, options);
      else if (part === "particles") body = partParticles(ctx, options);
      else if (part === "post") body = partPost(ctx, options);
    } catch (error) { ctx.err(part, error); body = { next: null }; body[part] = null; }
    Object.keys(body).forEach(function (k) { record[k] = body[k]; });
    if (record.next === undefined) record.next = null;
    section(ctx, record, "clockEnd", function () { return readClockEnd(ctx, directors); }, "always");
    return finish(ctx, record);
  }

  // ------------------------------------------------------------------ probe (metadata only)
  function classInfo(entry) {
    var found = lookupEntry(entry, null);
    resolved[entry.key] = found ? found.fullName : null;
    var out = { key: entry.key, requested: entry.candidates.slice(0, 4), found: !!found };
    if (!found) return out;
    var klass = found.klass;
    out.fullName = found.fullName;
    try { out.assembly = klass.assemblyName || (klass.image && klass.image.assembly && klass.image.assembly.name) || null; } catch (_) { out.assembly = null; }
    out.parents = [];
    var p = klass.parent, guard = 0;
    while (p && guard++ < 6) { out.parents.push(klassName(p)); p = p.parent; }
    try { out.unityObject = unityObjectClass(klass); } catch (_) { out.unityObject = null; }
    try { out.component = classIsA(klass, H.findClass("UnityEngine.Component", true)); } catch (_) { out.component = null; }
    out.fields = [];
    var k = klass, depth = 0;
    while (k && depth++ < 6 && out.fields.length < 64) {
      if (/^(UnityEngine|System)(\.|$)/.test(k.namespace || "") && k !== klass) break;
      (k.fields || []).forEach(function (f) {
        if (out.fields.length >= 64) return;
        var typeClass = null;
        try { typeClass = f.type.class; } catch (_) {}
        out.fields.push({ name: f.name, type: f.type.name, offset: f.offset, static: !!f.isStatic, declaredIn: klassName(k),
          valueType: typeClass ? !!typeClass.isValueType : null, enum: typeClass ? !!typeClass.isEnum : null });
      });
      k = k.parent;
    }
    if (entry.unity) {
      out.methods = {};
      var className = found.fullName;
      (ALLOW[className] || []).forEach(function (name) {
        var argc = (SIG[className + "::" + name] || []).length;
        try { out.methods[name] = !!klass.tryMethod(name, argc); } catch (_) { out.methods[name] = false; }
      });
    }
    return out;
  }
  function layoutSelfCheck(ctx) {
    var out = { ok: false };
    var cams = cameraCensus(ctx), main = cams.filter(function (c) { return c.role === "main"; })[0] || cams[0];
    if (!main) { out.error = "no active camera"; return out; }
    out.camera = main.info.path;
    var proj = inv(ctx, "UnityEngine.Camera", "get_projectionMatrix", main.object, []);
    var rawProj = raw(ctx, proj, 16, "layout.projection", 9);
    out.projectionRaw = rawProj;
    out.m32Field = num(ctx, Number(proj.field("m32").value), "layout.m32", 9);
    out.m23Field = num(ctx, Number(proj.field("m23").value), "layout.m23", 9);
    out.m00Field = num(ctx, Number(proj.field("m00").value), "layout.m00", 9);
    out.m32Raw = rawProj[11]; out.m23Raw = rawProj[14]; out.m00Raw = rawProj[0];
    out.columnMajor = rawProj[11] === out.m32Field && rawProj[14] === out.m23Field && rawProj[0] === out.m00Field;
    out.perspectiveSane = rawProj[11] === -1 && rawProj[15] === 0;
    var position = inv(ctx, "UnityEngine.Transform", "get_position", trOf(ctx, main.object), []);
    out.vec3Raw = raw(ctx, position, 3, "layout.position", 9);
    out.vec3Field = ["x", "y", "z"].map(function (axis) { return num(ctx, Number(position.field(axis).value), "layout.position." + axis, 9); });
    out.vec3Match = out.vec3Raw.every(function (v, i) { return v === out.vec3Field[i]; });
    out.ok = out.columnMajor && out.vec3Match;
    return out;
  }
  function probe(options) {
    var ctx = new Ctx("full", { budget: options.budget || { soft: 2000, hard: 4000 } });
    var per = Math.max(1, Math.min(8, Number(options.perChunk) || 8)), chunk = Math.max(0, Number(options.chunk) || 0);
    var entries = CLASS_TABLE.slice(chunk * per, chunk * per + per), out = { kind: "probe", chunk: chunk, chunks: Math.ceil(CLASS_TABLE.length / per),
      extensionVersion: EXT_VERSION, classes: [] };
    entries.forEach(function (entry) {
      try { out.classes.push(classInfo(entry)); } catch (error) { out.classes.push({ key: entry.key, found: false, error: short(error) }); }
    });
    if (chunk === 0 && options.layout !== false) {
      try { out.layoutSelfCheck = layoutSelfCheck(ctx); } catch (error) { out.layoutSelfCheck = { ok: false, error: short(error) }; }
    }
    if (chunk === 0) {
      try { var o = initOffsets(); out.objectLayout = { m_CachedPtr: o.cachedPtr, m_InstanceID: o.instanceId }; } catch (error) { out.objectLayout = { error: short(error) }; }
    }
    out.resolved = {};
    Object.keys(resolved).forEach(function (k) { out.resolved[k] = resolved[k]; });
    out.done = (chunk + 1) * per >= CLASS_TABLE.length;
    return finish(ctx, out);
  }

  globalThis.QA_MVDUMP_EXT = Object.freeze({ version: EXT_VERSION, parts: PARTS.slice(), deny: DENY.source,
    allow: JSON.parse(JSON.stringify(ALLOW)), classTable: JSON.parse(JSON.stringify(CLASS_TABLE)), caps: JSON.parse(JSON.stringify(CAPS)),
    budgets: JSON.parse(JSON.stringify(BUDGET)) });
  rpc.exports.mvruntimeprobe = function (options) {
    requireReady();
    options = options || {};
    return H.onMain(function () { return probe(options); });
  };
  rpc.exports.mvruntime = function (options) {
    requireReady();
    options = options || {};
    if (PARTS.indexOf(String(options.part || "frame")) < 0) throw new Error("MVDUMP_UNKNOWN_PART:" + options.part);
    return H.onMain(function () { return sample(options); });
  };
})();
