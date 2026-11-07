/* Pure numeric provenance policy. This module performs no Unity/Frida calls. */
(function (scope) {
    "use strict";
    const id = value => Number.isSafeInteger(value) && value !== 0;
    const invocation = value => Number.isSafeInteger(value) && value > 0;
    const ownerKeys = ["ownerComponentId", "ownerGameObjectId", "ownerTransformId"];
    const validOwner = value => value.typedOwnerVerified === true && ownerKeys.every(key => id(value[key])) &&
        new Set(ownerKeys.map(key => value[key])).size === ownerKeys.length;
    class RinaSpawnBindings {
        constructor({allowedNames, maxBindings = 32}) {
            if (!Array.isArray(allowedNames) || allowedNames.length !== 2 || new Set(allowedNames).size !== 2 ||
                !allowedNames.every(name => typeof name === "string" && /^ch(?:9999|0209)_co0040_member$/.test(name)) ||
                !Number.isSafeInteger(maxBindings) || maxBindings < 1 || maxBindings > 256) throw Error("BINDING_POLICY_CONFIG_INVALID");
            this.allowedNames = new Set(allowedNames);
            this.maxBindings = maxBindings;
            this.byRoot = new Map();
            this.byOwner = new Map();
            this.generations = new Map();
            this.issued = new WeakSet();
            this.completed = new WeakSet();
            this.generation = 0;
        }
        removeRoot(rootId) {
            const old = this.byRoot.get(rootId);
            if (!old) return [];
            this.byRoot.delete(rootId);
            if (this.byOwner.get(old.ownerComponentId) === rootId) this.byOwner.delete(old.ownerComponentId);
            return [old];
        }
        begin(input) {
            const invalidated = [];
            let generation = null;
            if (id(input.ownerComponentId)) {
                const previous = this.byOwner.get(input.ownerComponentId);
                if (previous !== undefined) invalidated.push(...this.removeRoot(previous));
                if (!this.generations.has(input.ownerComponentId) && this.generations.size >= 256) throw Error("OWNER_GENERATION_LIMIT");
                if (++this.generation > 1000000) throw Error("SPAWN_GENERATION_LIMIT");
                generation = this.generation;
                this.generations.set(input.ownerComponentId, generation);
            }
            const accepted = input.contextVerified === true && validOwner(input) && input.typedPrefabVerified === true &&
                id(input.prefabId) && !ownerKeys.some(key => input[key] === input.prefabId) &&
                this.allowedNames.has(input.prefabName) && input.usePrefab === false && invocation(input.spawnInvocation);
            const frame = Object.freeze({accepted, generation,
                ownerComponentId: id(input.ownerComponentId) ? input.ownerComponentId : null,
                ownerGameObjectId: id(input.ownerGameObjectId) ? input.ownerGameObjectId : null,
                ownerTransformId: id(input.ownerTransformId) ? input.ownerTransformId : null,
                prefabId: accepted ? input.prefabId : null, originalPrefabName: accepted ? input.prefabName : null,
                spawnInvocation: invocation(input.spawnInvocation) ? input.spawnInvocation : null});
            this.issued.add(frame);
            return {frame, invalidated};
        }
        complete(frame, result) {
            const invalidated = id(result.rootTransformId) ? this.removeRoot(result.rootTransformId) : [];
            const issued = frame != null && this.issued.has(frame) && !this.completed.has(frame);
            if (issued) this.completed.add(frame);
            const valid = issued && frame.accepted && result.contextVerified === true && result.typedResultVerified === true &&
                result.name === "Model" && validOwner(result) && id(result.rootGameObjectId) && id(result.rootTransformId) &&
                new Set([frame.prefabId, result.rootGameObjectId, result.rootTransformId,
                    ...ownerKeys.map(key => result[key])]).size === 6 && result.parentTransformId === frame.ownerTransformId &&
                ownerKeys.every(key => result[key] === frame[key]) && this.generations.get(frame.ownerComponentId) === frame.generation;
            if (!valid) return {binding: null, invalidated};
            if (this.byRoot.size >= this.maxBindings) throw Error("SPAWN_BINDING_LIMIT");
            const binding = Object.freeze({policy: "prefab-owner-root-v1", spawnInvocation: frame.spawnInvocation,
                originalPrefabName: frame.originalPrefabName, prefabId: frame.prefabId,
                prefabClass: "UnityEngine.GameObject", ownerClass: "LLAS.Scene.Live.Components.LiveCoreMember",
                typedOwnerVerified: true, typedPrefabVerified: true, typedResultVerified: true, usePrefab: false,
                ownerComponentId: frame.ownerComponentId, ownerGameObjectId: frame.ownerGameObjectId,
                ownerTransformId: frame.ownerTransformId, rootGameObjectId: result.rootGameObjectId,
                rootTransformId: result.rootTransformId, parentTransformId: result.parentTransformId});
            this.byRoot.set(binding.rootTransformId, binding);
            this.byOwner.set(binding.ownerComponentId, binding.rootTransformId);
            return {binding, invalidated};
        }
        lookup(input) {
            if (input.contextVerified !== true || input.name !== "Model" || !validOwner(input) ||
                !id(input.rootTransformId) || !id(input.rootGameObjectId)) return null;
            const binding = this.byRoot.get(input.rootTransformId);
            if (!binding || binding.rootGameObjectId !== input.rootGameObjectId ||
                input.parentTransformId !== binding.parentTransformId ||
                !ownerKeys.every(key => input[key] === binding[key]) ||
                this.byOwner.get(binding.ownerComponentId) !== binding.rootTransformId) return null;
            return binding;
        }
        clear() {
            this.byRoot.clear(); this.byOwner.clear(); this.generations.clear();
            this.issued = new WeakSet(); this.completed = new WeakSet();
        }
    }
    scope.RinaSpawnBindings = RinaSpawnBindings;
    if (typeof module !== "undefined" && module.exports) module.exports = {RinaSpawnBindings};
})(globalThis);
