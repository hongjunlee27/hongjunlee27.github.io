Conference Tracker 검색 개선판 (2026-10)
====================================

교체할 파일은 딱 두 개입니다.

1) scripts/update_conferences.py
   -> VS Code의 hongjunlee27.github.io/scripts/ 폴더에 복사하여 기존 파일 덮어쓰기.

2) conferences/verified_events.json
   -> VS Code의 hongjunlee27.github.io/conferences/ 폴더에 새 파일로 추가.
   기존 conferences/events.json은 삭제하거나 덮어쓰지 마세요. 과거 학회 목록을 보존하는 데이터입니다.

기존 메인 index.html, conferences/index.html, .github/workflows/update-conferences.yml는 수정할 필요 없습니다.

VS Code 터미널에서 프로젝트 폴더에서:
  git add scripts/update_conferences.py conferences/verified_events.json
  git commit -m "Fix conference discovery and dates"
  git push origin main

GitHub Actions -> Update and deploy conferences -> Run workflow -> main -> Run workflow를 수동 실행하세요.

로그의 'Search and update archive'에
- QUERY ... {N} results
- Successful searches: ... new entries: ... total archived: ...
- Reasons for excluded pages: {...}
가 나타납니다. 2027년 공식 학회 2건은 verified_events.json에 포함되어 있으므로
처음에는 검색 결과가 없어도 2건이 추가되어야 합니다. 기존 events.json의 항목은 절대로 삭제되지 않습니다.

주의:
- Tavily API Secret `TAVILY_API_KEY`가 GitHub Repository Actions Secrets에 있어야 합니다.
- API 검색 정확도를 보장하지 않습니다. 검색된 학회 날짜는 주최 측 홈페이지에서 확인하세요.
- 이름/연구 분야 조건을 페이지에서 판별하는 방법은 휴리스틱이며 발표 프로그램이 PDF에만 있다면 누락될 수 있습니다.
- 연구자명은 행사 페이지에 있더라도 실제 발표자 여부를 100% 확인하지 않습니다.
- 기존 링크를 보관하지만 주최 측 웹사이트가 장차 닫히면 외부 링크가 끊길 수 있습니다.

수정 사항:
- 행사명에 'workshop/conference'가 없더라도 주최 페이지에 회의 증거가 있으면 인정.
- 연도별 개별 Tavily 검색 45회/주(15개 키워드 × 3년)로 분리.
- 날짜 범위, Indico 'Starts ... Ends ...', 신청 마감일과 개최 날짜 구분 개선.
- 깨지는 문자 인코딩 처리 개선.
- 검색 실패/제외 사유 집계.
- 공식 행사 2건에 대한 신뢰할 수 있는 초기 기록 추가.
