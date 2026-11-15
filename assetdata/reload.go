package assetdata

// ResetForReload clears loaded catalog state only after the host has drained
// every game request and closed the previous database engines.
func ResetForReload() {
	NameToLocale = map[string]string{}
	Metapack = map[string]*MetapackType{}
	Pack = map[string]*PackType{}
	loadedProfiles = 0
	wholeFileProfiles = map[string]profileMask{}
}
