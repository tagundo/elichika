#!/usr/bin/env bash
#
# Elichika 서버 업데이트 스크립트 (DB 보존)
#
# 보존 대상:
#   - serverdata.db, userdata.db          (파일)
#   - assets/db/gl/, assets/db/jp/        (디렉터리)
#
# 흐름: 데이터 백업 -> 코드/에셋 업데이트 & 빌드 -> 성공 시 데이터 복원
#       실패 시 백업은 상위 디렉터리에 그대로 남겨둠
#
# 주의: elichika 프로젝트 루트에서 실행할 것.

set -uo pipefail   # 미정의 변수/파이프 실패를 잡되, 조건문(&&,||) 오작동을 막기 위해 -e 는 쓰지 않음

# ---------------------------------------------------------------------------
# 0. 사전 점검 — 프로젝트 루트에서 실행되는지 확인
# ---------------------------------------------------------------------------
if [ ! -e .git ] || [ ! -d assets ]; then
    echo "ERROR: elichika 프로젝트 루트에서 실행해야 합니다 (.git / assets 가 보이지 않음)." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 0-1. 실행 중인 서버 종료
#   빌드/rebuild_assets 가 serverdata.db 등을 열기 때문에, 기존 인스턴스가
#   살아 있으면 "database is locked (SQLITE_BUSY)" 로 실패한다. 먼저 종료한다.
#
#   주의:
#   - Termux 에서는 `pkill -x elichika` 가 `./elichika` 실행 형태와 안 맞아 못 죽인다.
#   - 그래서 커맨드라인(-f)으로 매칭하고, SIGTERM 을 씹을 수 있으니 SIGKILL(-9) 로 죽인다.
#   - 패턴 '(^|/)elichika( |$)' 는 서버 바이너리(./elichika, /path/elichika)만 잡고,
#     이 업데이트 스크립트(update_elichika2)나 디렉터리명(elichika2)은 건드리지 않는다.
# ---------------------------------------------------------------------------
echo "==> Stopping any running elichika..."
pkill -9 -f '(^|/)elichika( |$)' 2>/dev/null || true
for _ in $(seq 1 10); do
    pgrep -f '(^|/)elichika( |$)' >/dev/null 2>&1 || break
    sleep 1
    pkill -9 -f '(^|/)elichika( |$)' 2>/dev/null || true
done
sleep 1   # 파일 락이 풀릴 시간을 준다

# ---------------------------------------------------------------------------
# 백업 경로 정의 (상위 디렉터리에 저장)
# ---------------------------------------------------------------------------
BACKUP_GL="../elichika_backup_gl"
BACKUP_JP="../elichika_backup_jp"
BACKUP_SERVER="../serverdata.db.backup"
BACKUP_USER="../userdata.db.backup"

# ---------------------------------------------------------------------------
# 1. 기존 백업 정리 (이전 실패 시 남은 파일 제거)
# ---------------------------------------------------------------------------
rm -rf "$BACKUP_GL" "$BACKUP_JP" "$BACKUP_SERVER" "$BACKUP_USER"

# ---------------------------------------------------------------------------
# 2. 데이터 백업 (디렉터리는 cp -r, 파일은 cp)
# ---------------------------------------------------------------------------
echo "==> Backing up databases..."
[ -d assets/db/gl ] && cp -r assets/db/gl "$BACKUP_GL"
[ -d assets/db/jp ] && cp -r assets/db/jp "$BACKUP_JP"
[ -f serverdata.db ] && cp serverdata.db "$BACKUP_SERVER"
[ -f userdata.db ]   && cp userdata.db   "$BACKUP_USER"

# 원본이 있었는데 백업이 안 만들어졌다면(디스크/권한 문제 등) 위험하므로 중단
backup_failed=0
{ [ -d assets/db/gl ] && [ ! -d "$BACKUP_GL" ]; }     && backup_failed=1
{ [ -d assets/db/jp ] && [ ! -d "$BACKUP_JP" ]; }     && backup_failed=1
{ [ -f serverdata.db ] && [ ! -f "$BACKUP_SERVER" ]; } && backup_failed=1
{ [ -f userdata.db ]   && [ ! -f "$BACKUP_USER" ]; }   && backup_failed=1
if [ "$backup_failed" -ne 0 ]; then
    echo "ERROR: 백업 생성 실패. 업데이트를 중단합니다 (원본은 그대로 보존됨)." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. 코드 / 서브모듈 업데이트 및 빌드
# ---------------------------------------------------------------------------
echo "==> Updating code and assets..."

# install.sh 가 elichika / elichika_utility.sh / shortcut.sh 에 chmod 를 하면
# git 이 실행권한 비트(100644->100755)를 "로컬 변경"으로 보고 pull 을 막는다.
# 모드 변경을 추적하지 않도록 해서 이 충돌을 방지한다.
git config core.fileMode false

update_ok=1
{
    git pull \
    && git submodule deinit -f assets \
    && git submodule update --init --recursive --checkout assets \
    && { CGO_ENABLED=0 go build -o elichika || go build -o elichika; } \
    && ./elichika rebuild_assets
} || update_ok=0

# ---------------------------------------------------------------------------
# 4. 결과 처리
# ---------------------------------------------------------------------------
if [ "$update_ok" -eq 1 ]; then
    echo "==> Restoring databases..."
    mkdir -p assets/db

    # [핵심] 대상 디렉터리가 이미 존재하면 mv 가 "교체"가 아니라 "그 안으로 이동(중첩)"이 된다.
    #        서브모듈 재체크아웃/rebuild_assets 후 gl·jp 가 기본본으로 다시 생겨 있을 수 있으므로,
    #        반드시 먼저 제거한 뒤 백업본을 옮긴다.
    if [ -d "$BACKUP_GL" ]; then
        rm -rf assets/db/gl
        mv "$BACKUP_GL" assets/db/gl
    fi
    if [ -d "$BACKUP_JP" ]; then
        rm -rf assets/db/jp
        mv "$BACKUP_JP" assets/db/jp
    fi

    # 파일은 mv -f 로 안전하게 덮어쓴다.
    [ -f "$BACKUP_SERVER" ] && mv -f "$BACKUP_SERVER" serverdata.db
    [ -f "$BACKUP_USER" ]   && mv -f "$BACKUP_USER"   userdata.db

    # 부가 스크립트 실행 (있을 때만)
    if [ -f ./bin/shortcut.sh ]; then
        chmod +x ./bin/shortcut.sh
        ./bin/shortcut.sh
    fi

    echo "==> Updated successfully with preserved databases!"
else
    echo "ERROR: 업데이트 실패! 백업은 다음 위치에 그대로 보존되어 있습니다:" >&2
    echo "  $BACKUP_GL" >&2
    echo "  $BACKUP_JP" >&2
    echo "  $BACKUP_SERVER" >&2
    echo "  $BACKUP_USER" >&2
    exit 1
fi
