# update the server while preserving databases:
# - serverdata.db, userdata.db
# - assets/db/gl/, assets/db/jp/

# 백업 디렉터리/파일 이름 정의 (상위 디렉터리에 저장)
BACKUP_GL="../elichika_backup_gl"
BACKUP_JP="../elichika_backup_jp"
BACKUP_SERVER="../serverdata.db.backup"
BACKUP_USER="../userdata.db.backup"

# 1. 기존 백업이 있다면 정리 (이전 실패 시 남은 파일 제거)
rm -rf "$BACKUP_GL" "$BACKUP_JP" "$BACKUP_SERVER" "$BACKUP_USER"

# 2. 데이터 백업 (디렉터리는 cp -r, 파일은 cp)
echo "Backing up databases..."
[ -d assets/db/gl ] && cp -r assets/db/gl "$BACKUP_GL"
[ -d assets/db/jp ] && cp -r assets/db/jp "$BACKUP_JP"
[ -f serverdata.db ] && cp serverdata.db "$BACKUP_SERVER"
[ -f userdata.db ] && cp userdata.db "$BACKUP_USER"

# 3. 코드 및 서브모듈 업데이트, 빌드
echo "Updating code and assets..."
git pull && \
git submodule deinit -f assets && \
git submodule update --init --recursive --checkout assets && \
(go build || CGO_ENABLED=0 go build) && \
./elichika rebuild_assets

# 4. 업데이트 성공 시 백업 데이터 복원
if [ $? -eq 0 ]; then
    echo "Restoring databases..."
    # assets/db 디렉터리가 없으면 생성
    mkdir -p assets/db
    # 디렉터리 복원 (백업이 존재할 경우에만)
    [ -d "$BACKUP_GL" ] && mv "$BACKUP_GL" assets/db/gl
    [ -d "$BACKUP_JP" ] && mv "$BACKUP_JP" assets/db/jp
    [ -f "$BACKUP_SERVER" ] && mv "$BACKUP_SERVER" serverdata.db
    [ -f "$BACKUP_USER" ] && mv "$BACKUP_USER" userdata.db

    chmod +rwx ./bin/shortcut.sh && \
    ./bin/shortcut.sh
    echo "Updated successfully with preserved databases!"
else
    echo "Error updating! Databases remain backed up at:"
    echo "  $BACKUP_GL, $BACKUP_JP, $BACKUP_SERVER, $BACKUP_USER"
fi
