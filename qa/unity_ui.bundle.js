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
  var result={musicRows:[],deckTabGroups:[],errors:[]};
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

function observeExistingMvState(screen) {
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
  var music=observeExistingMusicRowsAndMvTabs(screen,raycaster);result.musicRows=music.musicRows;result.deckTabGroups=music.deckTabGroups;result.errors=result.errors.concat(music.errors);
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
  query = query || {}; var screen = metadata(), state = observeExistingMvState(screen), matches = [];
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
  matches = matches.filter(function(entry) {var t=entry.target;return t.active && t.enabled && t.visible && t.groupsInteractable && t.blocksRaycasts && t.hit && t.hit.available && t.hit.hittable;});
  if (matches.length !== 1) throw new Error(JSON.stringify({error:"MV target absent, obscured or ambiguous",query:query,matches:matches.length,state:state,screen:screen}));
  return {timestampMs:Date.now(),screen:screen,target:matches[0].target,catalog:matches[0].cell,
    input:{method:"adb shell input tap",x:matches[0].target.center.x,y:matches[0].target.center.y},
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
    var observed = snapshot({ maxNodes: query.maxNodes || 1000, extraTypes: query.extraTypes || [], allSelectables: !!query.allSelectables, raycastText: true,
      customButtons: query.customButtons !== false, numericTestId: query.numericTestId });
    function matches(actual, expected) { return query.exact === false ? normalize(actual).indexOf(normalize(expected)) >= 0 : normalize(actual) === normalize(expected); }
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
    if (unique.length !== 1) throw new Error(JSON.stringify({ error: unique.length ? "Ambiguous active semantic UI targets" : "No active semantic UI target", query: query,
      matches: unique.slice(0, 12).map(function (node) { return { id: node.id, name: node.name, path: node.path, text: node.text, label: node.label, center: node.center }; }),
      screen: observed.screen, hitTest: observed.hitTest, diagnostics: observed.diagnostics }));
    return { timestampMs: observed.timestampMs, screen: observed.screen, target: unique[0],
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

