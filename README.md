# 🎵 Discord Music Bot

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![yt-dlp](https://img.shields.io/badge/yt--dlp-2024+-FF0000?logo=youtube&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

Discord 음악 봇입니다. 재생 제어, 사용자별 플레이리스트 관리, 재생 기록 기반 자동 DJ 모드를 제공합니다.

---

## ✨ 주요 기능

### 🎵 재생 엔진
- YouTube · SoundCloud 등 yt-dlp 지원 플랫폼 **검색어 및 URL** 모두 재생
- 파일 다운로드 없이 **직접 스트리밍** (FFmpeg `-vn` 오디오 추출)
- 네트워크 끊김 **자동 재연결** (`-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5`)
- 재생 시 봇 미입장 상태면 **자동 입장** 후 즉시 재생

### 📋 큐 · 재생 제어
- **서버별 독립** 대기열 — 여러 서버 동시 운영 시 서로 영향 없음
- 볼륨 0~100% **실시간 조절**, 서버별 별도 유지
- 1곡 반복 · 전체 반복 · 반복 없음 **3단계 순환 전환**
- 대기열 **무작위 셔플**, 특정 번호 곡 제거

### 🤖 자동 DJ 모드 _(핵심 차별점)_
대기열이 소진되기 전 자동으로 추천곡을 보충하는 지능형 연속 재생 모드

- 대기열 ≤ 5곡이면 **백그라운드에서 자동 보충** (목표 10곡 유지)
- **3단계 Fallback 추천 알고리즘**
  1. 내 플레이리스트 → 수록곡 아티스트 빈도 분석
  2. 재생 기록 DB → `play_count` 상위 아티스트 추출
  3. 기본 인기 차트 키워드 랜덤 선택 (위 두 단계 모두 실패 시)
- 최근 추천 URL 100개 캐시 · 아티스트당 3곡 상한으로 **고착화 방지**

### 🗂️ 플레이리스트 관리
- **사용자별 다중 플리** 생성 · 수정 · 삭제 (서버별 SQLite 테이블로 저장)
- 곡 추가 시 YouTube Data API v3 → yt-dlp **이중 검색 fallback**
- 수록곡 번호·범위 입력으로 **일괄 삭제** (`1, 3-7, 10` 형식 지원)
- 봇이 공통으로 있는 서버 간 **플리 내보내기 / 가져오기**

### 🎮 인터랙티브 UI
- 재생 시작마다 자동 출력되는 **버튼 리모컨** (⏯️ ⏭️ 🔀 🔁 ⏹️)
- 플리 선택 · 서버 선택을 위한 **드롭다운 메뉴**
- 20곡 단위 **페이지네이션** embed (이전 / 다음 버튼)
- 버튼 응답은 채널에 공개 전송, 비인가 클릭 오류만 **ephemeral** (클릭한 사람에게만 표시)

### ⚙️ 안정성 · 자동화
- 허용 채널 키워드(`노래`, `음악`, `music`, `봇`, `bot`) 기반 **채널 접근 제어**
- 봇 혼자 남으면 **3분 후 자동 퇴장** (누군가 입장 시 타이머 취소)
- **1시간 주기 백그라운드 정리** — 오래된 NowPlaying 메시지 · 비활성 길드 데이터 제거
- cog 재시작 없이 **핫 리로드** (`!리로드`, 오너 전용)

---

## 🏗️ 아키텍처

```
main.py                ← 봇 진입점, 전역 채널 가드, DB 초기화
  └── cogs/
       ├── music.py    ← MusicCog  : 재생 엔진, 큐, DJ 모드, UI
       └── database.py ← DatabaseCog: 플리 CRUD, 재생 기록

master_index.db        ← 전역 DB (플리 레지스트리 + 재생 기록)
guild_{id}.db          ← 서버별 DB (플레이리스트 테이블)
config.json            ← yt-dlp / FFmpeg / DJ 설정
```

### 모듈 의존 관계

```
MusicCog ──bot.get_cog()──► DatabaseCog
  재생 후 → add_to_play_history()
  DJ 추천 → get_user_playlists(), get_playlist_songs(), get_play_history()

DatabaseCog ──bot.get_cog()──► MusicCog
  플리 재생 → add_songs()
```

### 핵심 재생 흐름

```
!재생 <검색어>
  └─ queue에 추가
  └─ play_next() 호출 (재생 중 아닐 때)

play_next()
  ├─ 반복 모드 처리 (one: 큐 앞에 재삽입 / all: 순환 버퍼)
  ├─ _process_play() → yt-dlp (executor) → FFmpegPCMAudio → vc.play()
  ├─ DB에 재생 기록 저장
  └─ NowPlaying embed + MusicControlView 출력

DJ 모드 활성 시: 대기열 ≤ 5곡이면 비동기 백그라운드로 자동 보충
```

---

## 🤖 자동 DJ 모드

대기열이 소진되기 전 자동으로 추천곡을 채우는 지능형 모드입니다.

```
1순위: 내 플레이리스트 → 담긴 곡들의 아티스트 빈도 분석
2순위: 재생 기록     → play_count 상위 아티스트 추출
3순위: 기본 차트     → ["빌보드 핫 100", "Kpop 최신곡", ...] 중 랜덤 5개
```

- 최근 추천 URL 100개 캐시로 중복 방지
- 아티스트당 최대 3곡 상한 (고착화 방지)
- 검색 접미사 랜덤 선택(`"명곡"`, `"MV"`, `"라이브"` 등)으로 같은 곡 재추천 방지

---

## 🗄️ 데이터베이스 설계

### master_index.db (전역)

```sql
-- 플레이리스트 레지스트리
playlist_registry (
    user_id       TEXT,
    playlist_name TEXT,
    guild_id      TEXT,
    PRIMARY KEY (user_id, playlist_name)
)

-- 재생 기록 (DJ 모드 학습 데이터)
play_history (
    user_id     TEXT,
    guild_id    TEXT,
    song_title  TEXT,
    song_url    TEXT,
    artist      TEXT,
    play_count  INTEGER DEFAULT 1,    -- 중복 재생 시 upsert로 +1
    last_played TIMESTAMP,
    PRIMARY KEY (user_id, guild_id, song_url)
)
-- INDEX: (user_id, guild_id), (play_count DESC)
```

### guild_{id}.db (서버별)

```sql
-- 테이블명 = "{user_id}_{playlist_name}"
"{uid}_{pname}" (
    title TEXT,
    url   TEXT      -- YouTube 영구 URL
)
```

- WAL 모드 활성화로 동시 읽기 성능 확보
- `sanitize_name()`으로 플리 이름 정제, 테이블명 따옴표 이스케이프 (SQL Injection 방어)

---

## 🎮 인터랙티브 UI

### 재생 리모컨 (MusicControlView)

```
[ ⏯️ 재생/일시정지 ] [ ⏭️ 스킵 ] [ 🔀 셔플 ] [ 🔁 반복 모드 ] [ ⏹️ 나가기 ]
```

- `timeout=None` — 봇 재시작 전까지 만료되지 않음
- 버튼 응답은 채널 공개 전송, 비인가 클릭 오류만 ephemeral
- 새 곡 시작 시 이전 리모컨 자동 삭제 후 신규 출력

### 플레이리스트 드롭다운 (PlaylistSelect)

| 모드 | 동작 |
|---|---|
| `show_contents` | 수록곡 페이지네이션 표시 |
| `play` | 전체 곡을 대기열에 추가 |
| `delete` | 선택한 플리 삭제 |
| `edit` | 번호/범위 입력으로 곡 일괄 삭제 |
| `export` | 공통 서버 중 선택한 서버로 복사 |
| `import` | 다른 서버의 내 플리를 현재 서버로 가져오기 |

---

## 📋 명령어 목록

### 재생 제어

| 명령어 | 단축어 | 설명 |
|---|---|---|
| `!재생 [검색어/URL]` | `!노래` | 검색 또는 URL로 재생·대기열 추가 |
| `!입장` | `!노래봇` | 음성 채널 입장 |
| `!나가기` | `!나가`, `!ㅂㅂ`, `!disconnect`, `!leave` | 퇴장 및 상태 초기화 |
| `!스킵` | `!다음`, `!skip` | 현재 곡 건너뜀 |
| `!목록` | `!q`, `!queue` | 대기열 표시 |
| `!삭제 [번호]` | `!del`, `!remove`, `!제거` | 대기열 특정 곡 제거 |
| `!볼륨 [0-100]` | `!vol`, `!v` | 볼륨 설정 |
| `!셔플` | `!섞기`, `!shuffle` | 대기열 셔플 |
| `!반복` / `!전체반복` / `!반복종료` | `!1곡반복`, `!loop` / `!loopall` / `!unloop` | 반복 모드 전환 |

### DJ 모드

| 명령어 | 단축어 | 설명 |
|---|---|---|
| `!자동` | `!자동재생`, `!auto` | DJ 모드 ON (대기열 10곡 즉시 채움) |
| `!자동끄기` | `!자동해제`, `!autooff` | DJ 모드 OFF |
| `!추천` | `!추천곡`, `!recommend` | 현재 곡 기반 추천 5곡 표시 |
| `!상태` | `!status`, `!info`, `!정보` | 봇 상태 정보 표시 |

### 플레이리스트

| 명령어 | 설명 |
|---|---|
| `!플리생성 [이름]` | 플레이리스트 생성 |
| `!담기 [플리] [검색/URL]` | 곡 추가 (YouTube API → yt-dlp fallback) |
| `!플리재생 [이름]` | 플리 전곡 대기열에 추가 |
| `!플리내용 [이름]` (`!플리목록`) | 수록곡 확인 (페이지네이션) |
| `!플리수정 [이름]` | 곡 번호/범위 입력으로 일괄 삭제 |
| `!플리삭제 [이름]` | 플리 삭제 |
| `!내플리` / `!서버플리` | 플리 목록 조회 |
| `!플리내보내기 [이름]` | 다른 서버로 플리 복사 |
| `!플리불러오기` | 다른 서버의 내 플리 가져오기 |

---

## ⚙️ 설치 및 실행

### 요구사항

- Python 3.11+
- FFmpeg (PATH 등록 필요)
- Discord Bot Token
- (선택) YouTube Data API v3 Key

### 설치

```bash
git clone https://github.com/your-username/discord-music-bot.git
cd discord-music-bot
pip install -r requirements.txt
```

### 설정

```bash
# 봇 토큰
echo "YOUR_BOT_TOKEN" > token.txt

# YouTube API 키 (없으면 yt-dlp로 자동 fallback)
echo "YOUR_YOUTUBE_API_KEY" > youtube_key.txt
```

`config.json`에서 볼륨, DJ 추천 수, FFmpeg 옵션 등을 조정할 수 있습니다.

### 실행

```bash
python main.py
```

### 채널 설정

명령어는 채널명에 다음 키워드가 포함된 채널에서만 동작합니다:
`노래`, `음악`, `music`, `봇`, `bot`

---

## 🛠️ 기술 스택

| 분류 | 기술 |
|---|---|
| 언어 | Python 3.11+ |
| Discord | discord.py 2.x (Cog 아키텍처, Prefix Commands) |
| 오디오 | yt-dlp, FFmpeg (PCMVolumeTransformer, 스트리밍) |
| DB | SQLite (WAL 모드, 서버별 분리 + 전역 마스터 인덱스) |
| 비동기 | asyncio, `run_in_executor` (yt-dlp 블로킹 방지) |
| HTTP | aiohttp |

---

## 📁 프로젝트 구조

```
discord_Music_Bot2/
├── main.py              # 봇 진입점, 채널 가드, DB 초기화
├── cogs/
│   ├── music.py         # 재생 엔진, 큐, DJ 모드, UI 컴포넌트
│   └── database.py      # 플레이리스트 CRUD, 재생 기록
├── config.json          # yt-dlp / FFmpeg / DJ 설정
├── requirements.txt
├── token.txt            # (git 제외)
└── youtube_key.txt      # (git 제외, 선택)
```

---

## 📝 설계 원칙

- **서버 격리** — 재생 상태와 플레이리스트 DB를 `guild_id` 단위로 완전 분리
- **비동기 yt-dlp** — `run_in_executor`로 블로킹 추출을 스레드 풀에 위임, 이벤트 루프 차단 없음
- **Cog 간 통신** — `bot.get_cog()` 런타임 조회로 순환 임포트 방지
- **메모리 관리** — 1시간 주기 정리 태스크 + 길드 퇴장 시 즉시 `_cleanup_guild_data()`
- **설정 외부화** — ytdl/ffmpeg 옵션을 `config.json`으로 분리, cog 재시작 없이 조정 가능
