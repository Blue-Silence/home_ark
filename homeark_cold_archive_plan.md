# HomeArk：`/home` 冷归档与可恢复封存方案

> **HomeArk** = **Home Archival & Recovery Kit**  
> 面向 Linux 服务器 `/home` 目录的冷归档方案：将 `/home` 下所有**非隐藏的一级目录**封存为长期可读的归档集，并为每个归档提供完整性校验与文件级纠错能力。

---

## 1. 项目背景

服务器上的 `/home` 往往同时包含用户数据、项目代码、实验结果、配置文件、密钥材料、脚本以及其他长期有价值的数据。对于即将下线、迁移或不再频繁访问的服务器，仅做一次普通复制或单纯压缩并不足以满足长期保存需求：

- 普通复制缺少明确的归档边界，长期后难以确认当时到底保存了什么；
- 单个大压缩包虽然简单，但一旦局部损坏，影响范围大，恢复也不够灵活；
- 仅有校验和只能发现损坏，不能修复损坏；
- 使用小众专有归档格式，会增加多年后读取与迁移的不确定性。

因此，HomeArk 采用“**通用归档格式 + 显式清单 + 校验 + 纠错 + 多副本**”的分层设计，把一次性冷存档做成一套可以长期保存、独立验证、局部恢复的归档集。

---

## 2. 目标与非目标

### 2.1 目标

HomeArk 的目标是为 `/home` 生成一份适合长期离线保存的冷归档，满足以下要求：

1. **长期可读**  
   使用主流、开放、长期可获得的工具与格式，避免依赖专有生态。

2. **归档范围明确**  
   仅归档 `/home` 下所有**非隐藏一级目录**；被选中的目录内部内容完整保留，包括其内部隐藏文件与隐藏目录。

3. **元数据尽量保真**  
   保存目录树、权限、属主、组、符号链接、硬链接、ACL、扩展属性、稀疏文件等重要文件系统信息。

4. **可验证**  
   为最终归档集生成强校验清单，可在多年后确认文件是否保持不变。

5. **可修复**  
   为每个归档文件生成独立的 PAR2 纠错数据，在一定范围内可以修复局部损坏。

6. **局部恢复友好**  
   可以只恢复某一个一级目录，而不需要解开整个 `/home`。

7. **操作可复现**  
   归档过程、工具版本、源主机信息、包含与排除清单均被记录，便于未来审计和恢复。

### 2.2 非目标

HomeArk **不是**以下类型的系统：

- 不是日常增量备份系统；
- 不是在线高可用存储系统；
- 不是文件版本控制系统；
- 不是对整块磁盘或文件系统做镜像；
- 不负责替代异地副本、介质轮换或灾难恢复策略。

若需求变为“持续备份、可回滚到任意日期、自动去重”，应另行采用 Borg、restic、ZFS snapshot 等方案；HomeArk 只负责**最终封存**。

---

## 3. 总体设计

HomeArk 将一次冷归档拆成四层：

```text
原始数据层   /home 下非隐藏一级目录
归档层       每个一级目录 -> 一个 tar.zst 文件
校验层       整个归档集 -> SHA256SUMS
纠错层       每个 tar.zst -> 一组 PAR2 文件
```

最终输出不是单个巨大文件，而是一套结构化的**归档集**。

### 3.1 为什么按一级目录拆分

HomeArk 不将整个 `/home` 压成一个超大归档，而是将每个非隐藏一级目录分别归档：

- 降低单点损坏影响范围；
- 支持按目录独立恢复；
- 支持按目录独立校验与修复；
- 便于处理体量差异很大的用户目录或项目目录；
- 归档结构与源目录结构自然对应，未来更容易理解。

例如：

```text
/home/
├── alice/
├── bob/
├── projects/
├── .cache/
└── README
```

最终归档：

```text
DATA/alice.tar.zst
DATA/bob.tar.zst
DATA/projects.tar.zst
```

其中：

- `/home/alice`、`/home/bob`、`/home/projects` 被归档；
- `/home/.cache` 被排除，因为它是 `/home` 顶层的隐藏目录；
- `/home/README` 被排除，因为它不是目录；
- 但 `/home/alice/.ssh`、`/home/alice/.config` 等内部隐藏内容仍会被保留。

---

## 4. 技术选型

### 4.1 主归档格式：`tar.zst`

HomeArk 采用：

- `tar` 作为归档容器；
- `zstd` 作为压缩层。

原因：

- `tar` 是 Linux/Unix 生态中最通用的归档格式之一；
- GNU tar 能保存 ACL、扩展属性、数字 UID/GID、稀疏文件等重要元数据；
- `zstd` 是现代开放压缩格式，压缩率与速度平衡良好，并支持内容校验；
- `tar.zst` 不依赖小众私有格式，长期可迁移性较好。

### 4.2 校验机制：`SHA-256`

对最终归档集中的关键文件生成 `SHA256SUMS`：

- 所有 `DATA/*.tar.zst`；
- 所有 `PAR2/*`；
- 关键清单文件与说明文件。

`SHA256SUMS` 用于确认归档文件在复制、搬运和长期保存后是否保持不变。

### 4.3 纠错机制：`PAR2`

HomeArk 为每个 `tar.zst` 单独生成一组 PAR2 文件：

```text
alice.tar.zst
alice.tar.zst.par2
alice.tar.zst.vol*.par2
```

设计原则：

- **每个归档独立保护**，不把多个目录混成一个纠错集；
- 若某个归档损坏，只需验证和修复对应目录；
- 未来即使只取出一个目录的归档，也仍然具有独立修复能力。

第一版实现默认使用常见 `par2` 命令行接口（如 `par2cmdline` 提供的 `par2` 命令）。默认只显式配置冗余比例 `PARITY_PERCENT`，块大小、recovery volume 分布等高级参数交由工具自动决定。

若未来遇到超大归档、文件数量过多或 PAR2 生成速度不可接受，再增加显式块大小与 volume 参数。

### 4.4 为什么不默认分卷

HomeArk 默认**不对归档文件进行额外分卷**。

原因：

- PAR2 本身按块处理文件损坏，不需要先把大文件人为切成小文件；
- 不分卷可以降低文件数量和操作复杂度；
- 分卷会增加搬运、重组和命名管理的风险。

仅在以下场景中考虑分卷：

- 目标介质或文件系统存在单文件大小限制；
- 单个一级目录的归档文件大到无法放入目标介质；
- 人工希望按介质容量切分。

---

## 5. 归档范围定义

### 5.1 默认纳入规则

HomeArk 默认归档所有满足以下条件的路径：

- 位于 `/home` 下一级；
- 是真实目录；
- 目录名不以 `.` 开头。

等价规则：

```bash
find /home -mindepth 1 -maxdepth 1 -type d ! -name '.*'
```

### 5.2 默认排除规则

默认排除：

- `/home` 顶层隐藏目录，如 `/home/.cache`；
- `/home` 顶层普通文件；
- `/home` 顶层符号链接，除非明确扩展规则。

### 5.2.1 显式排除规则

HomeArk 支持显式排除指定的 `/home` 顶层目录。

配置方式：

```bash
EXCLUDE_TOP_LEVEL_NAMES="cache,tmp,old project"
```

命令行方式：

```bash
homeark.py inventory --config homeark.conf --exclude tmp --exclude "old project"
homeark.py archive --config homeark.conf --exclude tmp --exclude "old project"
```

显式排除只按 `/home` 顶层目录名做精确匹配，不递归匹配内部路径。若 `/home/alice` 被纳入归档，则 `/home/alice/tmp` 不会因为 `--exclude tmp` 被排除。

若目录名本身包含逗号，建议使用命令行 `--exclude` 多次传入，避免配置文件中的逗号分隔产生歧义。

### 5.3 重要说明

一旦某个一级目录被纳入归档，**其内部所有内容都将被完整保留**，包括：

- `.ssh`；
- `.config`；
- `.local`；
- `.git`；
- 其他任何内部隐藏文件或目录。

HomeArk 的“排除隐藏目录”只作用于 `/home` 的**第一层**，不会递归删除用户目录内部的隐藏内容。

### 5.4 挂载点处理原则

HomeArk **不对 `/home` 内部挂载点做特殊处理**。

若已纳入目录内部存在以下对象：

- 单独挂载的数据盘；
- bind mount；
- NFS、SSHFS 等远程挂载；
- 其他运行时挂载目录；

HomeArk 会把它们当作当前目录树中的普通内容处理。换言之，归档范围以运行归档命令时 `/home` 下实际可见、可读取的目录树为准。

实现上，默认 **不使用** `--one-file-system`，也不主动跳过 mount point。

### 5.5 归档文件名映射

HomeArk 支持 `/home` 顶层目录名中出现空格、制表符、换行、百分号、非 ASCII 字符或其他特殊字符。

为避免这些目录名直接进入归档文件名、TSV 字段或 shell 命令时造成歧义，实际归档文件名使用**可逆转义名**：

- 真实目录名在机器可读清单中使用同一套可逆转义表示；
- 归档文件名使用目录名 UTF-8 字节序列的百分号转义形式；
- 安全集合建议为 `A-Z`、`a-z`、`0-9`、`.`、`_`、`-`；
- 其他字节写作 `%HH`，其中 `HH` 为两位大写十六进制；
- 字符 `%` 本身也必须转义为 `%25`，以保证映射可逆。

示例：

```text
alice        -> DATA/alice.tar.zst
my project   -> DATA/my%20project.tar.zst
data%old     -> DATA/data%25old.tar.zst
实验数据      -> DATA/%E5%AE%9E%E9%AA%8C%E6%95%B0%E6%8D%AE.tar.zst
```

恢复脚本应以 `archive-index.tsv` 为准，通过真实目录名定位对应的转义归档文件，而不是要求用户手动输入转义名。

所有机器可读 manifest 中若出现源目录名，也应使用同一套 `percent-utf8` 表示；面向人工阅读的清单可以额外提供显示名，但不得作为脚本解析依据。

---

## 6. 输出目录结构

归档输出目录命名建议：

```text
homeark-<hostname>-<YYYY-MM-DD>/
```

示例：

```text
homeark-gpu-node-01-2026-05-10/
├── README.md
├── SHA256SUMS
├── MANIFEST/
│   ├── archive-index.tsv
│   ├── included-dirs.txt
│   ├── excluded-top-level.txt
│   ├── source-tree.txt
│   ├── host-info.txt
│   ├── mount-info.txt
│   ├── tool-versions.txt
│   └── archive-run.log
├── DATA/
│   ├── alice.tar.zst
│   ├── bob.tar.zst
│   └── projects.tar.zst
└── PAR2/
    ├── alice.tar.zst.par2
    ├── alice.tar.zst.vol000+*.par2
    ├── bob.tar.zst.par2
    ├── bob.tar.zst.vol000+*.par2
    └── projects.tar.zst.*.par2
```

### 6.1 `MANIFEST/archive-index.tsv`

建议字段：

```text
dir_name_escaped	source_path_escaped	archive_file	archive_bytes	parity_percent	created_at
alice	%2Fhome%2Falice	DATA/alice.tar.zst	123456789	10	2026-05-10T15:00:00+09:00
```

### 6.2 `MANIFEST/included-dirs.txt`

记录实际纳入的 `/home` 一级目录名称。机器可读版本应使用 `percent-utf8` 转义名；若需要人工查看，可额外生成显示用清单。

### 6.3 `MANIFEST/excluded-top-level.txt`

记录 `/home` 顶层中未纳入归档的对象，至少包括：

- 顶层隐藏目录；
- 顶层普通文件；
- 顶层符号链接；
- 其他非目录对象。

这样未来可以区分“有意排除”与“意外漏掉”。

### 6.4 `MANIFEST/source-tree.txt`

记录归档前 `/home` 顶层结构，便于未来审计。

### 6.5 `MANIFEST/host-info.txt`

建议记录：

- 主机名；
- 归档时间；
- 操作系统；
- 内核版本；
- 当前时区；
- 操作者；
- 源路径。

### 6.6 `MANIFEST/mount-info.txt`

记录 `/home` 及其下方挂载情况，避免未来无法判断某些数据是否来自独立文件系统、bind mount 或网络挂载。

### 6.7 `MANIFEST/tool-versions.txt`

记录：

- `tar --version`；
- `zstd --version`；
- `par2 -V` 或等价版本信息；
- `sha256sum --version`。

### 6.8 `MANIFEST/archive-run.log`

保存脚本运行日志，包含：

- 实际执行命令；
- 每个目录开始和结束时间；
- 警告与错误；
- 最终统计。

### 6.9 输出目录创建规则

归档输出目录必须是一次运行独占的新目录。

默认规则：

- `OUTPUT_ROOT` 必须位于 `SOURCE_ROOT` 之外；
- 若最终输出目录已经存在，`homeark.py archive` 默认直接失败；
- 不自动覆盖旧归档；
- 不默认续跑或混合写入已有归档集。

这样可以避免把归档输出重新归入源目录，也避免新旧结果混在同一归档集中。

---

## 7. 纠错与副本策略

### 7.1 推荐冗余参数

HomeArk 推荐：

| 场景 | PAR2 冗余 |
|---|---:|
| 至少两份独立物理副本 | 20% |
| 介质质量一般，或希望更保守 | 15% |
| 只有一份物理副本 | 不推荐；若不得已，至少 20% |

推荐默认值：

```text
PAR2 redundancy = 20%
physical copies = at least 2
```

### 7.2 为什么 PAR2 不能替代第二份副本

PAR2 能修复：

- 文件的局部损坏；
- 部分块丢失；
- 在冗余范围内的少量错误。

PAR2 不能解决：

- 整块硬盘损坏；
- 介质丢失；
- 归档目录整体误删；
- 所有原始文件与 PAR2 文件同时丢失。

因此，冷归档至少应保留两份独立副本，最好分属不同物理设备，重要场景下进一步做异地保存。

---

## 8. 归档前检查

### 8.1 一致性责任

HomeArk **不主动保证源数据在归档期间的一致性**。

操作者负责在归档前确认 `/home` 已处于适合冷归档的状态，例如相关用户、服务、任务已经停止，或归档期间产生的数据变化可以接受。

若归档过程中源文件仍在变化，最终归档结果以工具读取到的实际内容为准，可能不对应任何单一时间点。

推荐但不强制的做法：

1. 若 `/home` 位于支持快照的文件系统或卷管理层上，优先从只读快照归档；
2. 若无法做快照，选择业务空闲窗口；
3. 尽量停止会持续写入 `/home` 的任务，避免归档过程跨越多个不一致时间点。

### 8.2 挂载点记录

HomeArk 不因挂载点改变归档行为，但仍建议记录 `/home` 内部挂载情况，便于未来解释归档范围。

归档前可记录 `/home` 内部是否存在：

- 单独挂载的数据盘；
- bind mount；
- NFS/SSHFS 等远程挂载；
- 临时挂载目录。

记录方式建议：

```bash
findmnt -R /home
```

### 8.3 体量评估

归档前应估计：

- 每个一级目录的逻辑大小；
- 每个一级目录的实际占用；
- 目标介质剩余容量；
- 归档后加上 PAR2 冗余所需的总容量。

示例：

```bash
du -sh /home/* 2>/dev/null
```

更稳妥时应使用与纳入规则一致的脚本生成大小报告。

### 8.4 运行身份

为了尽量保存属主、组、ACL、扩展属性、特殊文件和所有可读内容，`homeark.py archive` 默认要求以 `root` 身份运行。

恢复时若需要还原数字 UID/GID、权限、ACL 与扩展属性，`homeark.py restore` 也应以 `root` 身份运行。

`homeark.py inventory` 与 `homeark.py verify` 可以由普通用户运行，但普通用户可能无法读取所有清单信息或验证受限路径。

### 8.5 输出位置检查

归档前必须检查输出位置：

- `OUTPUT_ROOT` 不得位于 `SOURCE_ROOT` 内部；
- 最终输出目录不得已存在；
- `SOURCE_ROOT` 与 `OUTPUT_ROOT` 应解析为绝对路径后再比较；
- 若检查失败，归档脚本应拒绝继续运行。

例如，`SOURCE_ROOT=/home` 时，`OUTPUT_ROOT=/home/user/archive` 是非法位置。

---

## 9. 归档流程

### 9.1 高层流程

```text
1. 创建归档输出目录
2. 记录主机信息、工具版本和挂载信息
3. 枚举 /home 顶层对象
4. 生成 included-dirs 与 excluded-top-level 清单
5. 对每个纳入目录：
   5.1 生成 tar.zst
   5.2 为该 tar.zst 生成 PAR2
   5.3 记录索引项
6. 对整个归档集生成 SHA256SUMS
7. 执行校验：
   7.1 sha256sum -c
   7.2 par2 verify
   7.3 至少做一次试解压或目录级抽查
8. 操作者自行将归档集复制到第二份独立介质
9. 操作者在第二份副本上再次执行 SHA-256 校验
```

HomeArk 脚本默认只负责生成与验证归档集；第二份物理副本的复制、保存、轮换和异地策略由操作者自行负责。

### 9.2 归档命令模板

对单个目录 `alice`：

```bash
sudo tar \
  --acls \
  --xattrs \
  --xattrs-include='*' \
  --numeric-owner \
  --sparse \
  -C /home \
  -cpf - alice \
| zstd -T0 -10 --check -o DATA/alice.tar.zst
```

说明：

- `-C /home` 使归档内部路径保持为 `alice/...`，而不是绝对路径；
- `--numeric-owner` 保存数字 UID/GID；
- `--acls`、`--xattrs`、`--xattrs-include='*'`、`--sparse` 用于尽量保留 Linux 文件系统语义；
- `--check` 让 zstd 帧自带内容校验；多数新版 `zstd` 默认启用该校验，但 HomeArk 仍显式传入该参数。
- 默认压缩等级建议为 `-10`，在压缩率、速度和内存占用之间保持较稳妥的平衡；需要更高压缩率时可通过 `ZSTD_LEVEL` 调整。

若当前 GNU tar 支持 SELinux 元数据保存参数，并且源系统启用了 SELinux，应在归档与恢复命令中启用对应参数；否则应在 `tool-versions.txt` 或 `archive-run.log` 中记录未启用原因。

### 9.3 PAR2 命令模板

```bash
par2 create -B"$ARCHIVE_DIR" -r20 PAR2/alice.tar.zst.par2 DATA/alice.tar.zst
```

其中 `-r20` 来自 `PARITY_PERCENT=20`。`-B"$ARCHIVE_DIR"` 将归档集根目录设为 PAR2 的 datafile basepath，使 `PAR2/*.par2` 可以保护 `DATA/*.tar.zst`。第一版默认不显式设置 PAR2 block size 或 recovery volume 切分参数。

### 9.4 SHA-256 清单命令模板

```bash
find DATA PAR2 MANIFEST -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum > SHA256SUMS
```

### 9.5 错误处理策略

HomeArk 默认采用**严格错误策略**：

- 任一目录归档命令失败，则本次归档运行失败；
- 任一文件读取失败、权限不足、归档过程中消失或发生变化，都必须记录到 `archive-run.log`；
- 若 `tar`、`zstd`、`par2` 或 `sha256sum` 返回非零状态，脚本不得把该归档集标记为成功；
- 已生成但未通过校验的归档文件应保留用于排查，不自动删除；
- 最终摘要应明确列出成功目录、失败目录和需要人工复核的警告。

如果未来需要“尽量归档能读到的内容”，可以作为显式的宽松模式扩展；默认冷归档不采用宽松模式。

---

## 10. 校验流程

### 10.1 归档完成后立即校验

```bash
sha256sum -c SHA256SUMS
```

### 10.2 验证 PAR2

对每个归档执行：

```bash
par2 verify -B"$ARCHIVE_DIR" PAR2/alice.tar.zst.par2 DATA/alice.tar.zst
```

### 10.3 抽样试读

至少选择若干归档执行：

```bash
zstd -t DATA/alice.tar.zst
zstd -dc DATA/alice.tar.zst | tar -tf - >/dev/null
```

对极其重要的归档，建议进行完整试解压到临时目录并与预期结构比对。

默认验证强度：

- `sha256sum -c`：全量执行；
- `par2 verify`：全量执行；
- `zstd -t`：全量执行；
- `zstd -dc ... | tar -tf -`：默认抽样执行，可配置为全量执行。

### 10.4 定期复检

冷存档不应“封完即忘”。建议：

- 每 6–12 个月做一次 `sha256sum -c`；
- 若介质长期离线，至少在迁移、复制、上架、下架时做完整校验；
- 发现损坏后，优先比对第二份副本；若仅为局部损坏，再使用 PAR2 修复。

---

## 11. 恢复流程

### 11.1 恢复前验证

```bash
sha256sum -c SHA256SUMS
```

若某个归档校验失败：

```bash
par2 verify -B"$ARCHIVE_DIR" PAR2/alice.tar.zst.par2 DATA/alice.tar.zst
par2 repair -B"$ARCHIVE_DIR" PAR2/alice.tar.zst.par2 DATA/alice.tar.zst
```

也可以使用 HomeArk 的显式修复命令：

```bash
homeark.py repair "$ARCHIVE_DIR" alice
homeark.py repair "$ARCHIVE_DIR" --all
```

`repair` 会对选中的 `DATA/*.tar.zst` 执行 PAR2 修复，并在修复后重新执行 `zstd -t` 与全局 `sha256sum -c SHA256SUMS`。

### 11.2 查看归档内容

```bash
zstd -dc DATA/alice.tar.zst | tar -tvf -
```

### 11.3 恢复到指定目录

```bash
mkdir -p /restore-target
zstd -dc DATA/alice.tar.zst \
| sudo tar \
    --acls \
    --xattrs \
    --xattrs-include='*' \
    --numeric-owner \
    -C /restore-target \
    -xpf -
```

默认情况下，`homeark.py restore` 应拒绝恢复到已存在且非空的目标目录，避免覆盖或混合现有数据。若未来需要合并恢复或覆盖恢复，应通过显式选项启用，并在恢复日志中记录。

恢复脚本应允许用户输入真实目录名，例如：

```bash
homeark.py restore 实验数据 /restore-target
```

脚本内部负责将真实目录名转换为 `percent-utf8` 转义名，并通过 `MANIFEST/archive-index.tsv` 定位对应归档文件。用户不应被要求手动输入 `DATA/%E5%AE%9E%E9%AA%8C%E6%95%B0%E6%8D%AE.tar.zst` 这样的转义文件名。

可选提供面向高级用法的 `--escaped-name` 参数，允许直接用 manifest 中的转义名定位归档。

恢复脚本也应支持全部恢复：

```bash
homeark.py restore "$ARCHIVE_DIR" --all /restore-target
```

全部恢复时，脚本应先对所有待恢复归档执行 PAR2 verify 或 repair；全部通过后，再把所有归档解开到同一个空目标目录中。由于每个 `tar.zst` 内部保留一级目录名，最终结果会形成 `/restore-target/alice`、`/restore-target/bob` 等目录。

恢复完成后，应检查：

- 目录结构；
- 权限；
- 属主；
- 特殊文件；
- 关键配置文件；
- 必要时比对文件级清单。

---

## 12. 跨平台兼容性

HomeArk 使用的 `tar.zst`、`SHA256SUMS` 和 `PAR2` 都是普通文件，适合在不同操作系统之间保存、复制和迁移。

但 HomeArk 面向的是 Linux `/home` 冷归档，其完整语义包括：

- 数字 UID/GID；
- Unix 权限位；
- 符号链接、硬链接；
- ACL；
- 扩展属性；
- SELinux 相关元数据；
- 稀疏文件；
- FIFO、设备文件等特殊对象。

这些语义无法在 Windows/NTFS 上完整表达。因此，HomeArk 的跨平台定位如下：

- **Linux**：推荐用于生成归档、完整验证和完整保真恢复；
- **Windows**：可以用于保存、复制、搬运归档集，也可以在安装相应工具后执行 SHA-256/PAR2 校验；
- **Windows 普通解压**：可以提取普通文件内容，但不保证 Linux 元数据、链接和特殊文件完整恢复；
- **WSL**：可以用于查看和部分操作归档，但若恢复目标位于 Windows 文件系统挂载路径下，也不应视为完整保真恢复。

结论：

> HomeArk 的归档文件本身跨平台可保存、可校验、可读取；但 Linux `/home` 的完整保真恢复应在 Linux 环境和支持相应语义的文件系统上完成。

---

## 13. 可选增强

### 13.1 文件级清单

除归档级 SHA-256 外，还可以为源文件生成逐文件清单：

```text
MANIFEST/source-files.sha256
```

适用场景：

- 需要未来逐文件核验；
- 数据集、论文材料、实验结果等对单文件真实性要求较高；
- 希望恢复后逐文件比对。

代价：

- 初次归档前需要额外完整读取所有文件；
- 对超大目录会增加时间成本。

### 13.2 加密层

若归档介质会离开可信环境，应额外加密。建议把加密作为**外层封装**，例如：

```text
alice.tar.zst -> alice.tar.zst.age
```

但要注意：

- 一旦引入加密，密钥管理就成为长期恢复的一部分；
- 必须把密钥备份策略与归档策略一起设计；
- 若没有明确的保密需求，不应为了“看起来更安全”而无意识增加未来恢复风险。

### 13.3 分卷

仅在以下情况启用：

- 目标介质单文件大小受限；
- 人工希望按介质容量拆分；
- 单个一级目录本身极大。

启用后需要同步扩展：

- 文件命名规则；
- 重组流程；
- PAR2 是保护“分卷集合”还是保护“单个归档原文件”；
- 恢复说明。

默认方案中不启用。

### 13.4 更细粒度拆分

若某些一级目录极大，可以在配置中为其定义二级拆分策略。例如：

```text
/home/projects -> 按子项目拆分
/home/datasets -> 按数据集拆分
```

但应避免无规则地自动递归拆分，否则归档结构会失去稳定边界。

---

## 14. 建议的配置文件

为了让脚本可复用，HomeArk 可以使用一个简单配置文件：

```bash
# homeark.conf
SOURCE_ROOT="/home"
OUTPUT_ROOT="/mnt/archive"
PARITY_PERCENT="20"
PAR2_BLOCK_SIZE="auto"
PAR2_VOLUME_LAYOUT="auto"
ZSTD_LEVEL="10"
INCLUDE_TOP_LEVEL_HIDDEN="false"
FOLLOW_TOP_LEVEL_SYMLINKS="false"
ENABLE_SOURCE_FILE_HASHES="false"
ARCHIVE_NAME_ENCODING="percent-utf8"
ERROR_POLICY="strict"
FULL_TAR_LIST_TEST="false"
EXCLUDE_TOP_LEVEL_NAMES=""
```

后续脚本应只读取配置，不要求用户每次手输复杂参数。

---

## 15. 建议的实现拆分

HomeArk 第一版使用 Python 实现命令行程序，不提供 shell wrapper。

Python 负责：

- 配置解析；
- `/home` 顶层对象枚举；
- `percent-utf8` 文件名转义；
- manifest 生成与读取；
- 输出目录安全检查；
- 日志与严格错误处理；
- 外部命令调度。

实际归档、压缩、纠错和校验仍调用系统工具：

- `tar`
- `zstd`
- `par2`
- `sha256sum`

命令行入口：

```text
homeark.py inventory # 仅生成归档前清单与容量报告
homeark.py archive   # 生成冷归档
homeark.py verify    # 校验归档集与 PAR2
homeark.py repair    # 使用 PAR2 修复指定或全部归档
homeark.py restore   # 恢复指定归档
```

第一批实现已覆盖：

- `homeark.py inventory`
- `homeark.py archive`
- `homeark.py verify`
- `homeark.py repair`
- `homeark.py restore`

这样可以覆盖归档范围预览、归档生成、归档验证、显式修复和指定目录恢复这条基础链路。

### 15.1 `homeark.py archive`

职责：

- 读取配置；
- 检查运行身份、输出位置和输出目录是否已存在；
- 创建归档目录；
- 生成清单；
- 对每个目录生成 `tar.zst` 与 `PAR2`；
- 生成索引、SHA256SUMS、日志。

### 15.2 `homeark.py verify`

职责：

- 执行 `sha256sum -c`；
- 对全部 PAR2 集执行 `par2 verify`；
- 全量执行 `zstd -t`；
- 抽样或按配置全量执行 tar 列表试读；
- 输出总结报告。

### 15.3 `homeark.py restore`

职责：

- 根据用户输入的真实目录名定位归档；
- 支持可选的转义名定位模式；
- 支持全部恢复；
- 可选先修复；
- 检查恢复目标目录是否安全；
- 恢复到指定目录；
- 输出恢复日志。

### 15.4 `homeark.py repair`

职责：

- 根据真实目录名或转义名定位归档；
- 可选对全部归档执行修复；
- 调用 PAR2 修复 `DATA/*.tar.zst`；
- 修复后执行 zstd 与 SHA-256 校验；
- 输出修复报告。

### 15.5 `homeark.py inventory`

职责：

- 列出将被纳入和排除的顶层对象；
- 统计每个待归档目录大小；
- 估算加上 PAR2 后的总空间需求；
- 在真正归档前给出预览。

---

## 16. 风险与边界

### 16.1 归档期间源数据变化

HomeArk 不提供快照、锁定或事务一致性机制。若归档过程中 `/home` 仍在持续写入，归档结果可能不对应任何单一时间点。操作者应自行保证源数据在归档期间处于静止或可接受状态；对重要数据，可在外部使用文件系统快照或业务停写窗口。

### 16.2 ACL / xattr 的跨系统恢复差异

即使归档中保存了 ACL、扩展属性和 SELinux 相关元数据，未来恢复到不同文件系统、不同发行版或不同安全策略环境时，也可能无法做到完全一致。

### 16.3 稀疏文件与特殊文件

HomeArk 会尽量保留稀疏文件语义，但对设备文件、socket、FIFO 等特殊对象的恢复效果仍依赖目标系统和权限。

### 16.4 纠错不是魔法

PAR2 只能在冗余范围内修复损坏，不能替代第二份副本，也不能挽救整套归档的完全丢失。

### 16.5 顶层符号链接默认不跟随

若 `/home` 下存在指向其他位置的顶层符号链接，默认不将其视为一级目录归档对象。否则可能把源范围意外扩大到 `/home` 之外。

### 16.6 输出目录误放入源目录

若归档输出目录位于 `/home` 内部，可能导致正在生成的归档被重新打包进自身所属的用户目录。HomeArk 默认拒绝这种配置。

### 16.7 第二副本由操作者负责

HomeArk 可以生成可验证、可修复的归档集，但不负责把归档集复制到第二块物理介质，也不负责介质轮换或异地保存。操作者必须自行完成第二副本，并在副本上执行校验。

### 16.8 恢复目标目录保护

为避免恢复过程覆盖或混合现有数据，HomeArk 默认拒绝恢复到已存在且非空的目录。操作者应为恢复准备一个新的空目录。

---

## 17. 推荐默认参数

```text
归档粒度：每个 /home 非隐藏一级目录一个 tar.zst
压缩算法：zstd
压缩等级：10
zstd checksum：开启
PAR2 冗余：20%
物理副本：至少 2 份
默认分卷：关闭
顶层隐藏目录：排除
显式排除目录：按顶层目录名精确匹配
内部隐藏内容：保留
顶层符号链接：不跟随
内部挂载点：按普通目录内容处理
一致性保证：由操作者在归档前自行保证
运行身份：archive/restore 默认要求 root
输出目录：必须位于源目录之外，且默认不得已存在
归档文件名：使用 percent-utf8 可逆转义
错误策略：严格模式，任一关键命令失败则本次运行失败
第二副本：由操作者自行复制和校验
验证强度：SHA256、PAR2、zstd 全量，tar 列表试读默认抽样
恢复目标：默认必须为空目录或不存在
恢复定位：默认接受真实目录名，脚本内部映射到 percent-utf8 归档名
PAR2 参数：第一版仅显式配置冗余比例，block size 和 volume layout 默认 auto
元数据：启用 ACL、xattr、完整 xattr include，SELinux 视工具与系统支持启用
文件级 SHA-256：默认关闭，可选开启
```

---

## 18. 最终判定标准

一次 HomeArk 冷归档完成，应同时满足：

1. `MANIFEST/included-dirs.txt` 与预期一致；
2. 每个纳入目录都对应一个 `DATA/*.tar.zst`；
3. 每个归档都对应一组 `PAR2/*`；
4. `sha256sum -c SHA256SUMS` 全部通过；
5. `par2 verify` 全部通过；
6. 至少一个归档完成试读或试解压；
7. 第二份物理副本校验通过；
8. `README.md`、索引和恢复说明完整；
9. 归档输出目录在离开源服务器后仍可独立理解和恢复。

---

## 19. 一句话方案

> HomeArk 将 `/home` 下所有非隐藏一级目录分别封装为开放、长期可读的 `tar.zst` 归档，为每个归档附加独立的 `PAR2` 纠错数据，并用全局 `SHA-256` 清单和多副本策略构成一套可验证、可修复、可局部恢复的长期冷存档。
