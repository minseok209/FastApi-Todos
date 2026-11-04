# 10주차: JMeter 실행 이미지 (amd64 / arm64 모두 동작)
#
# - 베이스: eclipse-temurin:17-jre-jammy
#   Docker 공식 openjdk 이미지는 2022-07 deprecated (보안 패치 없음) → 공식 대체재 temurin.
#   멀티아키 이미지라 arm64v8/ 접두사로 아키텍처를 고정할 필요가 없다. JMeter 5.6.3 은 Java 17 권장.
# - JMeter 5.6.3: 5.4.1 은 log4j-core 2.13.3 을 포함해 Log4Shell(CVE-2021-44228, 원격 코드 실행)에 노출된다.
FROM eclipse-temurin:17-jre-jammy

ENV JMETER_VERSION=5.6.3
ENV JMETER_HOME=/opt/apache-jmeter-${JMETER_VERSION}
ENV PATH=${JMETER_HOME}/bin:$PATH

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 다운로드 무결성 검증 — Apache 공식 sha512 와 비교해서 다르면 빌드 실패
# (가이드 원본의 URL 앞뒤 < > 는 노션 링크 표시가 복사된 것이라 그대로 쓰면 curl 이 실패한다)
RUN set -eux; \
    cd /tmp; \
    curl -fsSL -o jmeter.tgz    "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz"; \
    curl -fsSL -o jmeter.sha512 "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz.sha512"; \
    EXPECTED="$(grep -oE '[0-9a-fA-F]{128}' jmeter.sha512 | head -1 | tr 'A-F' 'a-f')"; \
    ACTUAL="$(sha512sum jmeter.tgz | cut -d' ' -f1)"; \
    [ "$EXPECTED" = "$ACTUAL" ] || { echo "checksum mismatch: $ACTUAL != $EXPECTED"; exit 1; }; \
    tar -xzf jmeter.tgz -C /opt/; \
    rm -f jmeter.tgz jmeter.sha512

# root 가 아닌 전용 계정으로 실행 (컨테이너 탈출 시 피해 범위를 줄인다)
# JMeter 폴더는 root 소유 그대로 두어 실행 중에 JMeter 자체를 바꿀 수 없게 하고, 작업 폴더(/jmeter)만 쓰기 허용
RUN useradd -u 1000 -m -s /bin/bash jmeter && \
    mkdir -p /jmeter && chown jmeter:jmeter /jmeter

USER jmeter

# 작업 폴더를 버전과 무관한 /jmeter 로 고정 → JMeter 버전을 올려도 Jenkinsfile 의 docker cp 경로는 그대로
WORKDIR /jmeter

CMD ["jmeter", "--version"]
