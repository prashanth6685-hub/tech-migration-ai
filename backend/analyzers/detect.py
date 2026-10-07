"""Technology / dependency / config detection from an extracted project.

Walks the file tree, reads manifests with stdlib parsers only, and returns a
DetectedStack of facts plus Finding signals that scoring.py turns into the
deterministic readiness score.
"""
from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["red", "yellow", "green"]

EXT_LANGUAGE = {
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cs": "C#",
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
}

TEST_PATTERNS = [
    re.compile(r".*Test\.java$"),
    re.compile(r".*Tests\.java$"),
    re.compile(r"test_.*\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r".*\.(test|spec)\.(ts|js|tsx|jsx)$"),
    re.compile(r".*Tests?\.cs$"),
    re.compile(r".*_test\.go$"),
]

CONFIG_NAMES = {
    "application.properties": "Spring",
    "application.yml": "Spring",
    "application.yaml": "Spring",
    "appsettings.json": "ASP.NET Core",
    "appsettings.Development.json": "ASP.NET Core",
    ".env": "env",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
}

MAX_SCAN_BYTES = 1_000_000  # only scan text files below this size
MAX_SCAN_FILES = 4000  # cap on content scanning (inventory may be larger)


class Dependency(BaseModel):
    name: str
    version: str = ""
    source: str = ""  # which manifest it came from


class LanguageInfo(BaseModel):
    name: str
    version: str = ""
    files: int = 0


class Finding(BaseModel):
    """A deterministic signal. deduction lowers the area score; green findings
    are strengths (deduction 0) shown on the dashboard."""

    severity: Severity
    area: str  # code|dependencies|database|security|testing|deployment|configuration
    title: str
    detail: str
    deduction: int = Field(ge=0, default=0)


class DetectedStack(BaseModel):
    languages: list[LanguageInfo] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    build_systems: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    orms: list[str] = Field(default_factory=list)
    testing_frameworks: list[str] = Field(default_factory=list)
    deployment: list[str] = Field(default_factory=list)
    ci: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    auth_hints: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    file_count: int = 0
    total_bytes: int = 0


def _read_text(path: Path) -> Optional[str]:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="strict")
    except Exception:
        return None  # binary or unreadable — skip, never execute


class _Detector:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.facts = DetectedStack()
        self._lang_files: dict[str, int] = {}
        self._lang_versions: dict[str, str] = {}
        self._scanned = 0

    # -- helpers ---------------------------------------------------------
    def _add(self, lst: list[str], value: str) -> None:
        if value and value not in lst:
            lst.append(value)

    def _find(self, severity: Severity, area: str, title: str, detail: str,
              deduction: int = 0) -> None:
        self.facts.findings.append(
            Finding(severity=severity, area=area, title=title,
                    detail=detail, deduction=deduction)
        )

    def _files(self, name: str) -> list[Path]:
        return [p for p in self.root.rglob(name) if p.is_file()]

    # -- main ------------------------------------------------------------
    def run(self) -> DetectedStack:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in EXT_LANGUAGE:
                lang = EXT_LANGUAGE[ext]
                self._lang_files[lang] = self._lang_files.get(lang, 0) + 1

        self._detect_manifests()
        self._detect_configs()
        self._detect_tests()
        self._detect_deployment()
        self._scan_contents()
        self._finalize_languages()
        self._score_findings()
        return self.facts

    # -- manifests -------------------------------------------------------
    def _detect_manifests(self) -> None:
        for pom in self._files("pom.xml"):
            self._add(self.facts.build_systems, "Maven")
            self._parse_pom(pom)
        for gradle in self._files("build.gradle") + self._files("build.gradle.kts"):
            self._add(self.facts.build_systems, "Gradle")
            self._parse_gradle(gradle)
        for pkg in self._files("package.json"):
            self._parse_package_json(pkg)
        for csproj in self.root.rglob("*.csproj"):
            if csproj.is_file():
                self._parse_csproj(csproj)
        for req in self._files("requirements.txt"):
            self._add(self.facts.build_systems, "pip")
            self._parse_requirements(req)
        for pyproj in self._files("pyproject.toml"):
            self._parse_pyproject(pyproj)
        if self._files("go.mod"):
            self._add(self.facts.build_systems, "Go modules")
        if self._files("Cargo.toml"):
            self._add(self.facts.build_systems, "Cargo")

    def _dep(self, name: str, version: str, source: str) -> None:
        if not any(d.name == name and d.source == source for d in self.facts.dependencies):
            self.facts.dependencies.append(Dependency(name=name, version=version, source=source))

    def _parse_pom(self, pom: Path) -> None:
        text = _read_text(pom)
        if not text:
            return
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}

        def find(tag: str) -> Optional[str]:
            el = root.find(f"m:{tag}", ns)
            if el is None:
                el = root.find(tag)
            return el.text.strip() if el is not None and el.text else None

        props = {}
        for p in root.findall("m:properties/*", ns) or root.findall("properties/*"):
            if p.tag and p.text:
                props[p.tag.split("}")[-1]] = p.text.strip()
        java_ver = (
            props.get("java.version")
            or props.get("maven.compiler.source")
            or props.get("maven.compiler.release")
            or ""
        )
        if java_ver:
            self._lang_versions["Java"] = java_ver

        parent = root.find("m:parent", ns) or root.find("parent")
        if parent is not None:
            aid = parent.find("m:artifactId", ns)
            ver = parent.find("m:version", ns)
            if aid is not None and "spring-boot-starter-parent" in (aid.text or ""):
                self._add(self.facts.frameworks, "Spring Boot")
                if ver is not None and ver.text:
                    self._dep("spring-boot", ver.text.strip(), "pom.xml")

        for dep in root.findall("m:dependencies/m:dependency", ns) or root.findall(
            "dependencies/dependency"
        ):
            gid = dep.find("m:groupId", ns)
            aid = dep.find("m:artifactId", ns)
            ver = dep.find("m:version", ns)
            gid_t = gid.text.strip() if gid is not None and gid.text else ""
            aid_t = aid.text.strip() if aid is not None and aid.text else ""
            ver_t = ver.text.strip() if ver is not None and ver.text else ""
            if not aid_t:
                continue
            self._dep(f"{gid_t}:{aid_t}" if gid_t else aid_t, ver_t, "pom.xml")
            low = aid_t.lower()
            if "spring-boot-starter" in low and "spring-boot-starter-parent" not in low:
                self._add(self.facts.frameworks, "Spring Boot")
            if "spring-security" in low:
                self._add(self.facts.auth_hints, "Spring Security")
            if "hibernate-core" in low or "hibernate-entitymanager" in low:
                self._add(self.facts.orms, "Hibernate")
            if "junit" in low or "jupiter" in low or "testng" in low:
                self._add(self.facts.testing_frameworks, "JUnit")
            if "mockito" in low:
                self._add(self.facts.testing_frameworks, "Mockito")
            if "postgresql" in low:
                self._add(self.facts.databases, "PostgreSQL")
            if "mysql-connector" in low:
                self._add(self.facts.databases, "MySQL")
            if "log4j" in low and "1.2" in ver_t:
                self._find("red", "dependencies", "Log4j 1.x is end-of-life",
                           f"pom.xml pins {aid_t} {ver_t}: EOL since 2015 with "
                           "known CVEs. Migrate to Log4j 2 or Logback before anything else.",
                           deduction=25)

    def _parse_gradle(self, gradle: Path) -> None:
        text = _read_text(gradle) or ""
        if "org.springframework.boot" in text:
            self._add(self.facts.frameworks, "Spring Boot")
        if "org.hibernate" in text:
            self._add(self.facts.orms, "Hibernate")
        if "junit" in text.lower():
            self._add(self.facts.testing_frameworks, "JUnit")
        m = re.search(r"sourceCompatibility\s*=\s*['\"]?([\d.]+)", text)
        if m:
            self._lang_versions["Java"] = m.group(1)

    def _parse_package_json(self, pkg: Path) -> None:
        text = _read_text(pkg)
        if not text:
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for name, ver in deps.items():
            self._dep(name, str(ver), "package.json")
            low = name.lower()
            if low == "react":
                self._add(self.facts.frameworks, "React")
            elif low == "@angular/core":
                self._add(self.facts.frameworks, "Angular")
            elif low == "next":
                self._add(self.facts.frameworks, "Next.js")
            elif low == "express":
                self._add(self.facts.frameworks, "Express")
            elif low == "vue":
                self._add(self.facts.frameworks, "Vue")
            elif low in ("jest", "vitest", "mocha"):
                self._add(self.facts.testing_frameworks, name)
            elif low == "typeorm":
                self._add(self.facts.orms, "TypeORM")
            elif low == "sequelize":
                self._add(self.facts.orms, "Sequelize")
            elif low == "prisma":
                self._add(self.facts.orms, "Prisma")
            elif low == "pg":
                self._add(self.facts.databases, "PostgreSQL")
            elif low in ("mysql", "mysql2"):
                self._add(self.facts.databases, "MySQL")
            elif low == "mongodb":
                self._add(self.facts.databases, "MongoDB")
            elif low == "passport":
                self._add(self.facts.auth_hints, "Passport.js")
        engines = data.get("engines", {})
        if engines.get("node"):
            self._lang_versions["JavaScript"] = str(engines["node"])
            self._lang_versions["TypeScript"] = str(engines["node"])

    def _parse_csproj(self, csproj: Path) -> None:
        text = _read_text(csproj)
        if not text:
            return
        self._add(self.facts.build_systems, "MSBuild/NuGet")
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return
        tf = root.find(".//TargetFramework")
        if tf is None:
            tf = root.find(".//TargetFrameworks")
        if tf is not None and tf.text:
            t = tf.text.strip()
            m = re.match(r"net(\d+)\.(\d+)", t)
            if m:
                self._lang_versions["C#"] = f".NET {m.group(1)}"
                self._add(self.facts.frameworks, "ASP.NET Core")
            elif t.lower().startswith("net4"):
                self._lang_versions["C#"] = ".NET Framework " + t[3:]
                self._find("yellow", "code", ".NET Framework target detected",
                           f"{csproj.name} targets {t}: migrating to modern .NET "
                           "means leaving Framework-only APIs behind.", deduction=10)
        for pr in root.findall(".//PackageReference"):
            name = pr.get("Include", "")
            ver = pr.get("Version", "")
            if name:
                self._dep(name, ver, csproj.name)
                low = name.lower()
                if "entityframeworkcore" in low:
                    self._add(self.facts.orms, "Entity Framework Core")
                if low == "xunit":
                    self._add(self.facts.testing_frameworks, "xUnit")
                if low == "nunit":
                    self._add(self.facts.testing_frameworks, "NUnit")
                if "serilog" in low:
                    self._add(self.facts.frameworks, "Serilog")

    def _parse_requirements(self, req: Path) -> None:
        text = _read_text(req) or ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"([A-Za-z0-9_.-]+)\s*([=<>!~]+.*)?", line)
            if not m:
                continue
            name, ver = m.group(1), (m.group(2) or "").strip()
            self._dep(name, ver, "requirements.txt")
            low = name.lower()
            if low == "django":
                self._add(self.facts.frameworks, "Django")
            elif low == "fastapi":
                self._add(self.facts.frameworks, "FastAPI")
            elif low == "flask":
                self._add(self.facts.frameworks, "Flask")
            elif low == "pytest":
                self._add(self.facts.testing_frameworks, "pytest")
            elif low == "sqlalchemy":
                self._add(self.facts.orms, "SQLAlchemy")
            elif low.startswith("psycopg"):
                self._add(self.facts.databases, "PostgreSQL")
            elif low == "pymongo":
                self._add(self.facts.databases, "MongoDB")

    def _parse_pyproject(self, pyproj: Path) -> None:
        text = _read_text(pyproj)
        if not text:
            return
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return
        self._add(self.facts.build_systems, "pyproject")
        deps = data.get("project", {}).get("dependencies", []) or list(
            data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys()
        )
        for dep in deps:
            m = re.match(r"([A-Za-z0-9_.-]+)", str(dep))
            if m:
                self._dep(m.group(1), "", "pyproject.toml")

    # -- configs / tests / deployment --------------------------------------
    def _detect_configs(self) -> None:
        for path in self.root.rglob("*"):
            if path.is_file() and path.name in CONFIG_NAMES:
                rel = str(path.relative_to(self.root))
                self._add(self.facts.config_files, rel)
        if len(self.facts.config_files) > 6:
            self._find("yellow", "configuration", "Configuration sprawl",
                       f"{len(self.facts.config_files)} config files found — "
                       "consolidate settings before migrating.", deduction=10)

    def _detect_tests(self) -> None:
        found = 0
        for path in self.root.rglob("*"):
            if path.is_file() and any(p.match(path.name) for p in TEST_PATTERNS):
                found += 1
        if found:
            self._find("green", "testing", f"{found} test files found",
                       "Existing tests can be converted to the target framework.", 0)
        else:
            self._find("yellow", "testing", "No test files detected",
                       "No automated tests to carry over — budget for writing "
                       "characterization tests before migrating.", deduction=30)

    def _detect_deployment(self) -> None:
        if self._files("Dockerfile"):
            self._add(self.facts.deployment, "Docker")
            self._find("green", "deployment", "Dockerfile present",
                       "Containerized already — the target deployment can reuse the pattern.", 0)
        if self._files("docker-compose.yml") or self._files("docker-compose.yaml"):
            self._add(self.facts.deployment, "Docker Compose")
        if (self.root / ".github" / "workflows").is_dir():
            self._add(self.facts.ci, "GitHub Actions")
        if self._files(".gitlab-ci.yml"):
            self._add(self.facts.ci, "GitLab CI")
        if self._files("Jenkinsfile"):
            self._add(self.facts.ci, "Jenkins")
        k8s = 0
        for yml in list(self.root.rglob("*.yaml")) + list(self.root.rglob("*.yml")):
            text = _read_text(yml) or ""
            if "kind: Deployment" in text:
                k8s += 1
        if k8s:
            self._add(self.facts.deployment, "Kubernetes")
        if self.facts.ci and "Docker" not in self.facts.deployment:
            self._find("yellow", "deployment", "CI without containers",
                       f"CI ({', '.join(self.facts.ci)}) builds bare artifacts — "
                       "containerizing is recommended for the target.", deduction=10)
        if not self.facts.deployment and not self.facts.ci:
            self._find("yellow", "deployment", "No deployment automation detected",
                       "No Dockerfile or CI found — deployment is manual or external.", deduction=20)

    # -- content scan (DB, secrets, auth, procs) -----------------------------
    def _scan_contents(self) -> None:
        db_patterns = [
            (r"jdbc:postgresql", "PostgreSQL"),
            (r"jdbc:mysql", "MySQL"),
            (r"postgresql://", "PostgreSQL"),
            (r"mongodb://", "MongoDB"),
            (r"Server=[^;]+;Database=", "SQL Server"),
        ]
        orm_imports = [
            ("jakarta.persistence", "JPA"),
            ("javax.persistence", "JPA"),
            ("org.hibernate", "Hibernate"),
            ("Microsoft.EntityFrameworkCore", "Entity Framework Core"),
            ("django.db", "Django ORM"),
            ("sqlalchemy", "SQLAlchemy"),
        ]
        secret_re = re.compile(
            r"(?i)(password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"]?([^'\"\s]{3,})"
        )
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if self._scanned >= MAX_SCAN_FILES:
                break
            if path.suffix.lower() not in EXT_LANGUAGE and path.name not in CONFIG_NAMES:
                if path.suffix.lower() not in (".xml", ".json", ".yml", ".yaml", ".properties", ".sql", ".gradle"):
                    continue
            text = _read_text(path)
            if not text:
                continue
            self._scanned += 1
            rel = str(path.relative_to(self.root))
            for pat, db in db_patterns:
                if re.search(pat, text):
                    self._add(self.facts.databases, db)
            for imp, orm in orm_imports:
                if imp in text:
                    self._add(self.facts.orms, orm)
            if re.search(r"(?i)CREATE\s+PROCEDURE", text):
                self._find("yellow", "database", "Stored procedures detected",
                           f"{rel} contains stored procedures — they must be "
                           "rewritten for the target database.", deduction=15)
                break  # one finding is enough
            if path.name in CONFIG_NAMES:
                for m in secret_re.finditer(text):
                    self._find("red", "security",
                               "Possible hardcoded secret in config",
                               f"{rel} sets '{m.group(1)}' inline — move to a "
                               "secret manager before migrating.", deduction=20)
                    break
            if re.search(r'MessageDigest\.getInstance\(\s*"MD5"\s*\)', text):
                self._find("red", "security", "Weak hash (MD5) in use",
                           f"{rel} uses MD5 — replace with a modern KDF during migration.",
                           deduction=15)
                break
            if "jjwt" in text or "jsonwebtoken" in text:
                self._add(self.facts.auth_hints, "JWT")
            if "spring-security" in text.lower():
                self._add(self.facts.auth_hints, "Spring Security")

    # -- finalize ------------------------------------------------------------
    def _finalize_languages(self) -> None:
        for lang, count in sorted(self._lang_files.items(), key=lambda x: -x[1]):
            self.facts.languages.append(
                LanguageInfo(name=lang, version=self._lang_versions.get(lang, ""), files=count)
            )

    def _score_findings(self) -> None:
        n_lang = len(self.facts.languages)
        if n_lang > 2:
            self._find("yellow", "code", "Polyglot codebase",
                       f"{n_lang} languages detected — migration must cover all of them.",
                       deduction=10)
        if not self.facts.frameworks:
            self._find("yellow", "code", "No framework detected",
                       "No known framework found — architecture analysis will be manual.",
                       deduction=15)
        if not self.facts.build_systems:
            self._find("yellow", "code", "No build system detected",
                       "No Maven/Gradle/npm/MSBuild project found.", deduction=10)
        if self.facts.file_count > 2000:
            self._find("yellow", "code", "Large codebase",
                       f"{self.facts.file_count} files — migrate incrementally, module by module.",
                       deduction=5)
        if len(self.facts.dependencies) > 80:
            self._find("yellow", "dependencies", "Large dependency surface",
                       f"{len(self.facts.dependencies)} dependencies — audit for "
                       "unused and deprecated ones.", deduction=10)
        if self.facts.orms:
            self._find("green", "database",
                       f"ORM in use ({', '.join(self.facts.orms)})",
                       "Entity mappings convert more cleanly than raw SQL.", 0)


def detect_project(root: Path, file_count: int = 0, total_bytes: int = 0) -> DetectedStack:
    """Run all detectors over an extracted project directory."""
    detector = _Detector(root)
    facts = detector.run()
    facts.file_count = file_count
    facts.total_bytes = total_bytes
    return facts
