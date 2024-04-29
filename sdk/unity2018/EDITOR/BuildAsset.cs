using UnityEngine;
using UnityEditor;

public class CreateAssetBundle : MonoBehaviour
{
    [MenuItem("Assets/Build Mesh AssetBundle")]
    static void BuildAssetBundle()
    {
        // Define the directory where you want to save the asset bundle
        string assetBundleDirectory = "Assets/COOKED";

        // Ensure the directory exists
        if (!System.IO.Directory.Exists(assetBundleDirectory))
        {
            System.IO.Directory.CreateDirectory(assetBundleDirectory);
        }

        // Define the name of your asset bundle
        string assetBundleName = "mesh_assets";

        // Collect the mesh assets you want to include in the bundle
        Object[] selectedObjects = Selection.objects;
        AssetBundleBuild[] buildMap = new AssetBundleBuild[1];

        // Setup the asset bundle build
        buildMap[0].assetBundleName = assetBundleName + ".unity3d";
        string[] assetNames = new string[selectedObjects.Length];

        for (int i = 0; i < selectedObjects.Length; i++)
        {
            assetNames[i] = AssetDatabase.GetAssetPath(selectedObjects[i]);
        }

        buildMap[0].assetNames = assetNames;

        // Build the asset bundles
        BuildPipeline.BuildAssetBundles(assetBundleDirectory, buildMap, BuildAssetBundleOptions.UncompressedAssetBundle, EditorUserBuildSettings.activeBuildTarget);
		Debug.Log("DONE");
    }
}
