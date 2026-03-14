package request

type SaveOverwriteDeckRequest struct {
	SourceDeckId int32 `json:"source_deck_id"`
	DestDeckId   int32 `json:"dest_deck_id"`
}
