package database

import "elichika/subsystem/managedcredential"

func init() {
	AddTable(managedcredential.Table, managedcredential.Record{})
}
