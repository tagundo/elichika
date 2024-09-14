using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
 
public class SkinnedMeshComponentWizard : ScriptableWizard
{
    public SkinnedMeshRenderer baseMesh;
    public List<SkinnedMeshRenderer> components;
 
    [MenuItem("Tools/Mesh/Generate Skinned Mesh Component")]
    protected static void CreateWizard()
    {
        DisplayWizard<SkinnedMeshComponentWizard>("Skinned Mesh Component Generation", "Generate");
    }
 
    protected void OnWizardCreate()
    {
        foreach (SkinnedMeshRenderer component in components)
        {
            Dictionary<int, int> boneMapping = new Dictionary<int, int>();
            for (int i = 0; i < component.bones.Length; i++)
            {
                Transform compBone = component.bones[i];
                if (compBone == null)
                {
                    Debug.Log("skip component bone " + i);
                    continue;
                }
                for (int j = 0; j < baseMesh.bones.Length; j++)
                {
                    Transform baseBone = baseMesh.bones[j];
                    if (baseBone == null)
                    {
                        //Debug.Log("skip base bone " + j);
                        continue;
                    }
                    if (compBone.name == baseBone.name)
                    {
                        Debug.Log("map " + i + " --> " + j + " [" + baseBone.name + "]");
                        boneMapping.Add(i, j);
                        break;
                    }
                }
            }
 
            //remap the bones
            BoneWeight[] weights = component.sharedMesh.boneWeights;
            int modified = 0;
            for (int i = 0; i < weights.Length; i++)
            {
                bool mod = false;
                BoneWeight weight = weights[i];
                if (weights[i].weight0 > 0.0) { weights[i].boneIndex0 = boneMapping[weight.boneIndex0]; mod = true; }
                if (weights[i].weight1 > 0.0) { weights[i].boneIndex1 = boneMapping[weight.boneIndex1]; mod = true; }
                if (weights[i].weight2 > 0.0) { Debug.LogError("Weight2 is greater than 0.0. Please set Limit Total weight to 2 in blender to avoid disappear mesh."); return; }
                if (weights[i].weight3 > 0.0) { Debug.LogError("Weight3 is greater than 0.0. Please set Limit Total weight to 2 in blender to avoid disappear mesh."); return; }
                if (mod) { modified++; }
            }
            Debug.Log("modified " + modified + " vertices");
 
            Vector3[] vertices = component.sharedMesh.vertices;
            Vector3 scale = component.transform.lossyScale;
            for (int i = 0; i < vertices.Length; i++)
            {
                Vector3 vertex = vertices[i];
                vertex.x *= scale.x;
                vertex.y *= scale.y;
                vertex.z *= scale.z;
                vertices[i] = vertex;
            }
 
            Mesh mesh = new Mesh
            {
                name = component.sharedMesh.name,
                vertices = vertices,
                uv = component.sharedMesh.uv,
                triangles = component.sharedMesh.triangles,
                bindposes = baseMesh.sharedMesh.bindposes,
                boneWeights = weights,
                normals = component.sharedMesh.normals,
                colors = component.sharedMesh.colors,
                tangents = component.sharedMesh.tangents
            };
            
            AssetDatabase.CreateAsset(mesh, Path.Combine("Assets", "Export", $"{mesh.name}_fixed.asset"));
        }
    }
 
    protected void OnWizardUpdate()
    {
        helpString = "Creates a new mesh based off the bone structure of a base mesh and ensures everything is in the correct order in the new mesh.";
        isValid = (baseMesh != null) && (components != null && components.Count > 0);
    }
}