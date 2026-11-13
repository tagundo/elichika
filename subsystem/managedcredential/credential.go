// Package managedcredential stores only newly chosen client passwords. Legacy
// bcrypt hashes cannot be reversed. The install key is private and is never
// included in an account export or derived from the shared game RSA key.
package managedcredential

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"

	"golang.org/x/crypto/bcrypt"
	"xorm.io/xorm"
)

const Table = "u_local_client_credential"
const KeyFile = ".local-webui-credentials.key"

var ErrUnavailable = errors.New("no current managed client password; explicitly set or generate a new password")

type Record struct {
	UserId     int32 `xorm:"pk 'user_id'"`
	Ciphertext []byte
}

type passwordHash struct{ Hash []byte }

func Generate() (string, error) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}

func installKey(path string, create bool) ([]byte, error) {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) && create {
		key := make([]byte, 32)
		if _, err = rand.Read(key); err != nil {
			return nil, err
		}
		var f *os.File
		f, err = os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err == nil {
			_, err = f.Write(key)
			if err == nil {
				err = f.Sync()
			}
			closeErr := f.Close()
			if err == nil {
				err = closeErr
			}
			if err != nil {
				return nil, err
			}
		} else if !os.IsExist(err) {
			return nil, err
		}
		info, err = os.Lstat(path)
	}
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("managed credential key must be a private regular file (0600)")
	}
	key, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(key) != 32 {
		return nil, errors.New("invalid managed credential key")
	}
	return key, nil
}

func aead(path string, create bool) (cipher.AEAD, error) {
	key, err := installKey(path, create)
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

func associatedData(userID int32) []byte {
	return []byte(fmt.Sprintf("elichika-client-password-v1:%d", userID))
}

// Set changes only the password hash and its encrypted local copy. The caller
// must use a transaction and explicitly commit it after the user's action.
func Set(db *xorm.Session, userID int32, password, keyPath string) error {
	if len(password) < 8 || len(password) > 72 {
		return errors.New("use a password between 8 and 72 bytes")
	}
	cipher, err := aead(keyPath, true)
	if err != nil {
		return err
	}
	nonce := make([]byte, cipher.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return err
	}
	encrypted := cipher.Seal(nonce, nonce, []byte(password), associatedData(userID))
	hash, err := bcrypt.GenerateFromPassword([]byte(password), 12)
	if err != nil {
		return err
	}
	rows, err := db.Table("u_pass_word").Where("user_id = ?", userID).AllCols().Update(passwordHash{Hash: hash})
	if err != nil {
		return err
	}
	if rows == 0 {
		_, err = db.Table("u_pass_word").Insert(&struct {
			UserId int32 `xorm:"pk 'user_id'"`
			Hash   []byte
		}{userID, hash})
		if err != nil {
			return err
		}
	}
	if _, err = db.Table(Table).Where("user_id = ?", userID).Delete(&Record{}); err != nil {
		return err
	}
	_, err = db.Table(Table).Insert(&Record{UserId: userID, Ciphertext: encrypted})
	return err
}

// Reveal verifies the current bcrypt hash on every call. A password changed in
// the game or another tool immediately makes a saved local credential unusable.
func Reveal(db *xorm.Session, userID int32, keyPath string) (string, error) {
	var record Record
	found, err := db.Table(Table).Where("user_id = ?", userID).Get(&record)
	if err != nil {
		return "", err
	}
	if !found {
		return "", ErrUnavailable
	}
	cipher, err := aead(keyPath, false)
	if err != nil {
		return "", ErrUnavailable
	}
	if len(record.Ciphertext) < cipher.NonceSize() {
		return "", ErrUnavailable
	}
	plain, err := cipher.Open(nil, record.Ciphertext[:cipher.NonceSize()], record.Ciphertext[cipher.NonceSize():], associatedData(userID))
	if err != nil {
		return "", ErrUnavailable
	}
	var current passwordHash
	found, err = db.Table("u_pass_word").Where("user_id = ?", userID).Get(&current)
	if err != nil {
		return "", err
	}
	if !found || bcrypt.CompareHashAndPassword(current.Hash, plain) != nil {
		return "", ErrUnavailable
	}
	return string(plain), nil
}
