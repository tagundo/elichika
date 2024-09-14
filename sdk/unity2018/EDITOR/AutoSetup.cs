using UnityEngine;
using UnityEditor;

public class ModelImportSettings : AssetPostprocessor
{
    void OnPreprocessModel()
    {
        ModelImporter modelImporter = assetImporter as ModelImporter;

        if (modelImporter != null)
        {
            // Update import settings
            bool settingsChanged = false;

            if (!modelImporter.isReadable)
            {
                modelImporter.isReadable = true;        // Read/Write Enabled = true
                settingsChanged = true;
            }

            if (modelImporter.weldVertices)
            {
                modelImporter.weldVertices = false;     // Weld Vertices = false
                settingsChanged = true;
            }

            if (modelImporter.useFileScale)
            {
                modelImporter.useFileScale = false;     // Convert Units = false
                settingsChanged = true;
            }

            // Save and reimport if any setting was changed
            if (settingsChanged)
            {
                modelImporter.SaveAndReimport();
            }
        }
    }
}
