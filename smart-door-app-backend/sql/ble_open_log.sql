-- 앱 BLE 서명 문열기 로그. DBA가 생성하고 앱 서버 계정에 SELECT, INSERT, UPDATE 권한을 부여한다.
-- 앱 서버가 패킷을 내줄 때 행을 만들고(ISSUE_DATE까지), 앱이 결과를 보고하면 같은 행(REQ_ID)에 결과를 채운다.
CREATE TABLE BLE_OPEN_LOG (
  REQ_ID      VARCHAR(36)  NOT NULL PRIMARY KEY,  -- 발급 때 만든 UUID
  RETRY_OF    VARCHAR(36)  NULL,                  -- 재시도면 첫 요청의 REQ_ID
  USER_ID     VARCHAR(50)  NOT NULL,              -- 학번 (학번 조회 실패 시 UPN 앞 50자)
  BLEID       VARCHAR(16)  NOT NULL,
  ROOM        VARCHAR(20)  NULL,
  CMD         VARCHAR(10)  NOT NULL,              -- open 등
  ISSUE       CHAR(1)      NOT NULL,              -- Y 발급 / N 권한 없음
  SIGNED      CHAR(1)      NULL,                  -- Y 서명 / N 원본
  KEY_VER     INT          NULL,
  CNT         BIGINT       NULL,
  APP_VER     VARCHAR(20)  NULL,
  OS          VARCHAR(20)  NULL,
  ISSUE_DATE  DATETIME     NOT NULL,
  RESULT      VARCHAR(12)  NULL,                  -- OK / NO_RESPONSE / BLE_FAIL / DOOR_FAIL
  STAGE       VARCHAR(20)  NULL,
  DOOR_RESP   VARCHAR(80)  NULL,                  -- 도어락 응답 hex
  ELAPSED_MS  INT          NULL,
  RESULT_DATE DATETIME     NULL,
  KEY IDX_BLE_OPEN_LOG_BLEID (BLEID, ISSUE_DATE),
  KEY IDX_BLE_OPEN_LOG_USER (USER_ID, ISSUE_DATE)
);
