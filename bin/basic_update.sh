#!/usr/bin/env bash
#
# Elichika 서버 업데이트 — 완전 재설치 + 데이터 보존 (Termux/Android)
#
# 절차:
#   1. userdata.db / serverdata.db / config.json / assets(gl,jp) 백업
#   2. 설치 디렉터리 완전 삭제 후 install.sh 로 재설치
#   3. 백업 복원
#   4. 에셋 재빌드 및 shortcut 실행
#   실패 시: 어디에 백업이 남아 있는지 안내하고 종료.
#
# 주의: 현재 elichika 설치 디렉터리(보통 elichika3, 테스트는 elichika3_test) 안에서 실행할 것.

set -uo pipefail   # -e 는 조건문(&&,||) 오작동 위험이 있어 일부러 미사용

# ---------------------------------------------------------------------------
# 0. 경로/브랜치 확정 — 절대경로로 고정해 cd 이후 경로 혼동을 원천 차단
# ---------------------------------------------------------------------------
INSTALL_DIR="$(pwd)"
INSTALL_NAME="$(basename "$INSTALL_DIR")"   # 보통 "elichika3" 또는 "elichika3_test"
PARENT_DIR="$(dirname "$INSTALL_DIR")"

if [ ! -x ./elichika ] && [ ! -d assets ]; then
    echo "ERROR: elichika 설치 디렉터리(예: elichika3) 안에서 실행하세요." >&2
    exit 1
fi

# 재설치 시 게임 CODE 는 현재 체크아웃된 브랜치(테스트 설치는 Test)에서 받아오지만,
# 헬퍼 스크립트(install.sh)는 항상 main 에서 받아온다(스크립트는 main 에만 유지).
CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
INSTALL_URL="https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/install.sh"

# 백업 경로 (전부 절대경로)
BK_USER="$PARENT_DIR/userdata.db.temp"
BK_SERVER="$PARENT_DIR/serverdata.db.temp"
BK_CONFIG="$PARENT_DIR/config.json.temp"
BK_GL="$PARENT_DIR/gl.temp"
BK_JP="$PARENT_DIR/jp.temp"

print_backup_locations() {
    echo "  $BK_USER"   >&2
    echo "  $BK_SERVER" >&2
    echo "  $BK_CONFIG" >&2
    echo "  $BK_GL"     >&2
    echo "  $BK_JP"     >&2
}

# ---------------------------------------------------------------------------
# 1. 이전 실패로 남은 백업 정리
# ---------------------------------------------------------------------------
rm -rf "$BK_USER" "$BK_SERVER" "$BK_CONFIG" "$BK_GL" "$BK_JP"

# ---------------------------------------------------------------------------
# 2. 백업 (cp 사용 — 재설치 전 단계가 실패해도 원본은 그대로 유지)
# ---------------------------------------------------------------------------
echo "==> Backing up databases..."
[ -f userdata.db ]   && cp -f userdata.db   "$BK_USER"
[ -f serverdata.db ] && cp -f serverdata.db "$BK_SERVER"
[ -f config.json ]   && cp -f config.json   "$BK_CONFIG"
[ -d assets/db/gl ]  && cp -r assets/db/gl  "$BK_GL"
[ -d assets/db/jp ]  && cp -r assets/db/jp  "$BK_JP"

# 원본이 있었는데 백업이 안 만들어졌으면(권한/용량 문제) 아무것도 지우지 않고 중단
fail=0
{ [ -f userdata.db ]   && [ ! -f "$BK_USER" ];   } && fail=1
{ [ -f serverdata.db ] && [ ! -f "$BK_SERVER" ]; } && fail=1
{ [ -f config.json ]   && [ ! -f "$BK_CONFIG" ]; } && fail=1
{ [ -d assets/db/gl ]  && [ ! -d "$BK_GL" ];     } && fail=1
{ [ -d assets/db/jp ]  && [ ! -d "$BK_JP" ];     } && fail=1
if [ "$fail" -ne 0 ]; then
    echo "ERROR: 백업 생성 실패. 아무것도 삭제하지 않고 중단합니다." >&2
    exit 1
fi
echo "    backup OK"

# ---------------------------------------------------------------------------
# 3. 완전 재설치
# ---------------------------------------------------------------------------
echo "==> Reinstalling $INSTALL_NAME (branch: $CUR_BRANCH) ..."
cd "$PARENT_DIR" || { echo "ERROR: '$PARENT_DIR' 로 이동 실패" >&2; exit 1; }

# install.sh 가 'rm -rf "$INSTALL_NAME"' 를 수행하므로 여기서 별도 삭제는 불필요.
# 같은 디렉터리/브랜치로 재설치되도록 INSTALL_NAME, BRANCH 를 넘긴다.
curl -L "$INSTALL_URL" | BRANCH="$CUR_BRANCH" INSTALL_NAME="$INSTALL_NAME" bash

# install.sh 는 내부 실패에도 0 으로 끝날 수 있으므로, 결과물(빌드 산출물)로 성공 판정한다.
if [ ! -x "$INSTALL_NAME/elichika" ]; then
    echo "ERROR: 재설치 실패 ($INSTALL_NAME/elichika 가 없음)." >&2
    echo "백업은 다음 위치에 그대로 보존되어 있습니다:" >&2
    print_backup_locations
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. 복원 (CWD = 부모. temp 파일은 부모에 있으므로 '../' 를 붙이지 않는다)
# ---------------------------------------------------------------------------
echo "==> Restoring databases..."

# 파일: mv -f 로 안전하게 덮어씀
[ -f "$BK_USER" ]   && mv -f "$BK_USER"   "$INSTALL_NAME/userdata.db"
[ -f "$BK_SERVER" ] && mv -f "$BK_SERVER" "$INSTALL_NAME/serverdata.db"
[ -f "$BK_CONFIG" ] && mv -f "$BK_CONFIG" "$INSTALL_NAME/config.json"

# 디렉터리: 대상이 이미 존재하면 mv 가 "그 안으로 중첩"되므로 먼저 제거 후 이동
mkdir -p "$INSTALL_NAME/assets/db"
if [ -d "$BK_GL" ]; then
    rm -rf "$INSTALL_NAME/assets/db/gl"
    mv "$BK_GL" "$INSTALL_NAME/assets/db/gl"
fi
if [ -d "$BK_JP" ]; then
    rm -rf "$INSTALL_NAME/assets/db/jp"
    mv "$BK_JP" "$INSTALL_NAME/assets/db/jp"
fi

# ---------------------------------------------------------------------------
# 5. 에셋 재빌드 및 마무리
# ---------------------------------------------------------------------------
cd "$INSTALL_NAME" || { echo "ERROR: '$INSTALL_NAME' 로 이동 실패" >&2; exit 1; }

echo "==> Rebuilding assets..."
if ./elichika rebuild_assets; then
    # 단축키 재생성 — 생성기는 main 에만 유지되므로 main 에서 받아 실행한다.
    _sc="$(mktemp 2>/dev/null || echo /tmp/elichika_shortcut.sh)"
    if curl -fsSL "https://raw.githubusercontent.com/tagundo/elichika/refs/heads/main/bin/shortcut.sh" -o "$_sc" && [ -s "$_sc" ]; then
        bash "$_sc"
    elif [ -f ./bin/shortcut.sh ]; then
        chmod +x ./bin/shortcut.sh
        ./bin/shortcut.sh
    fi
    rm -f "$_sc"
    echo "==> Updated successfully with preserved databases!"
else
    echo "ERROR: rebuild_assets 실패. 데이터는 복원됐지만 에셋 재빌드가 실패했습니다." >&2
    exit 1
fi
