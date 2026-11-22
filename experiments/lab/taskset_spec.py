"""任务集 v1 的规格（W2-2）。

**本文件是任务集 v1 的唯一真源**，也是全书唯一同时持有"正确实现"与"含缺陷实现"的地方。
正确实现不进任务目录——沙箱内文件对 Agent 可读，带了参考实现的任务会退化成复制。

每份规格含：
- `entry`：被考察的函数名（只用于索引与人工阅读）
- `statement`：任务陈述。**只描述应当成立的行为，不指出缺陷位置，不给修复方案**
- `fixed` / `buggy`：正确实现与含缺陷实现，两者的**函数签名必须一致**
- `cases`：每例 = 先执行的 `script` 行 + 最后断言的 `probe` 表达式。
  期望值由构建器用 `fixed` 跑出来，不在此手写，避免算错而写出一个"看起来对"的测试。

八个族，每族 8 题。族 = 一类失效模式，不是一类题目；族内同构是刻意的，
因为第 5 章要用"在 A 族上积累的经验迁到 B 族还剩多少"来区分两种拟合目标。
"""

from __future__ import annotations

# 划分只按族内编号，不做人工挑选（挑选会引入分布偏差）
SPLIT_BY_INDEX = {
    1: "train",
    2: "train",
    3: "select-valid",
    4: "select-valid",
    5: "regression",
    6: "regression",
    7: "sealed",
    8: "sealed",
}


def C(probe: str, *script: str) -> dict:
    """一个用例：先跑 script，最后断言 probe。"""
    return {"script": list(script), "probe": probe}


FAMILIES: dict[str, dict] = {
    # ------------------------------------------------------------------ 1
    "offbyone": {
        "failure_mode": "边界与差一：区间端点含/不含、循环上界",
        "variants": [
            dict(
                entry="sum_inclusive",
                statement="实现 sum_inclusive(a, b)：返回从 a 到 b 之间所有整数的和，两端都包含。",
                fixed=(
                    "def sum_inclusive(a, b):\n"
                    "    return sum(range(a, b + 1))\n"
                ),
                buggy=(
                    "def sum_inclusive(a, b):\n"
                    "    return sum(range(a, b))\n"
                ),
                cases=[
                    C("m.sum_inclusive(1, 5)"),
                    C("m.sum_inclusive(3, 3)"),
                    C("m.sum_inclusive(-2, 2)"),
                ],
            ),
            dict(
                entry="count_between",
                statement="实现 count_between(xs, lo, hi)：统计 xs 中落在 [lo, hi] 闭区间内的元素个数。",
                fixed=(
                    "def count_between(xs, lo, hi):\n"
                    "    return sum(1 for x in xs if lo <= x <= hi)\n"
                ),
                buggy=(
                    "def count_between(xs, lo, hi):\n"
                    "    return sum(1 for x in xs if lo < x < hi)\n"
                ),
                cases=[
                    C("m.count_between([1, 2, 3, 4, 5], 2, 4)"),
                    C("m.count_between([2, 2, 2], 2, 2)"),
                    C("m.count_between([0, 5, 9], 1, 5)"),
                ],
            ),
            dict(
                entry="last_k_sum",
                statement="实现 last_k_sum(xs, k)：返回 xs 最后 k 个元素之和；k 不大于 0 时返回 0。",
                fixed=(
                    "def last_k_sum(xs, k):\n"
                    "    return sum(xs[-k:]) if k > 0 else 0\n"
                ),
                buggy=(
                    "def last_k_sum(xs, k):\n"
                    "    return sum(xs[-k + 1:]) if k > 0 else 0\n"
                ),
                cases=[
                    C("m.last_k_sum([1, 2, 3, 4, 5], 2)"),
                    C("m.last_k_sum([1, 2, 3], 1)"),
                    C("m.last_k_sum([1, 2, 3, 4], 4)"),
                ],
            ),
            dict(
                entry="take_first",
                statement="实现 take_first(xs, n)：返回 xs 的前 n 个元素；不足 n 个时全部返回。",
                fixed=(
                    "def take_first(xs, n):\n"
                    "    return list(xs[:n])\n"
                ),
                buggy=(
                    "def take_first(xs, n):\n"
                    "    return list(xs[:n - 1])\n"
                ),
                cases=[
                    C("m.take_first([1, 2, 3, 4], 2)"),
                    C("m.take_first([1, 2], 5)"),
                    C("m.take_first([7, 8, 9], 3)"),
                ],
            ),
            dict(
                entry="drop_ends",
                statement="实现 drop_ends(xs)：去掉第一个和最后一个元素后返回剩下部分；元素不足两个时返回空列表。",
                fixed=(
                    "def drop_ends(xs):\n"
                    "    return list(xs[1:-1])\n"
                ),
                buggy=(
                    "def drop_ends(xs):\n"
                    "    return list(xs[1:-2])\n"
                ),
                cases=[
                    C("m.drop_ends([1, 2, 3, 4, 5])"),
                    C("m.drop_ends([1, 2, 3])"),
                    C("m.drop_ends([5, 6])"),
                ],
            ),
            dict(
                entry="adjacent_pairs",
                statement="实现 adjacent_pairs(xs)：返回相邻元素组成的二元组列表，如 [1,2,3] 得到 [(1,2),(2,3)]。",
                fixed=(
                    "def adjacent_pairs(xs):\n"
                    "    return [(xs[i], xs[i + 1]) for i in range(len(xs) - 1)]\n"
                ),
                buggy=(
                    "def adjacent_pairs(xs):\n"
                    "    return [(xs[i], xs[i + 1]) for i in range(len(xs) - 2)]\n"
                ),
                cases=[
                    C("m.adjacent_pairs([1, 2, 3])"),
                    C("m.adjacent_pairs([1, 2])"),
                    C("m.adjacent_pairs([1, 2, 3, 4])"),
                ],
            ),
            dict(
                entry="chunks",
                statement="实现 chunks(xs, n)：从头开始每 n 个元素切成一组，最后一组可以不足 n 个。",
                fixed=(
                    "def chunks(xs, n):\n"
                    "    return [xs[i:i + n] for i in range(0, len(xs), n)]\n"
                ),
                buggy=(
                    "def chunks(xs, n):\n"
                    "    return [xs[i:i + n] for i in range(1, len(xs), n)]\n"
                ),
                cases=[
                    C("m.chunks([1, 2, 3, 4, 5], 2)"),
                    C("m.chunks([1, 2, 3], 3)"),
                    C("m.chunks([1, 2, 3, 4], 2)"),
                ],
            ),
            dict(
                entry="in_closed",
                statement="实现 in_closed(v, lo, hi)：判断 v 是否落在闭区间 [lo, hi] 内。",
                fixed=(
                    "def in_closed(v, lo, hi):\n"
                    "    return lo <= v <= hi\n"
                ),
                buggy=(
                    "def in_closed(v, lo, hi):\n"
                    "    return lo <= v < hi\n"
                ),
                cases=[
                    C("m.in_closed(5, 1, 5)"),
                    C("m.in_closed(3, 3, 3)"),
                    C("m.in_closed(0, 1, 5)"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 2
    "mutabledefault": {
        "failure_mode": "共享可变状态：可变默认参数与模块级容器的累积与别名",
        "variants": [
            dict(
                entry="append_to",
                statement="实现 append_to(x, items=None)：返回把 x 追加到 items 之后的新列表；items 缺省时从空列表开始。每次调用互不影响。",
                fixed=(
                    "def append_to(x, items=None):\n"
                    "    items = [] if items is None else list(items)\n"
                    "    items.append(x)\n"
                    "    return items\n"
                ),
                buggy=(
                    "def append_to(x, items=[]):\n"
                    "    items.append(x)\n"
                    "    return items\n"
                ),
                cases=[
                    C("m.append_to(1)"),
                    C("m.append_to(2)", "m.append_to(1)"),
                    C("m.append_to(3)", "m.append_to(1)", "m.append_to(2)"),
                ],
            ),
            dict(
                entry="add_tag",
                statement="实现 add_tag(tag, tags=None)：返回加入 tag 之后的全部标签（升序排列的列表）；tags 缺省时从空集合开始。每次调用互不影响。",
                fixed=(
                    "def add_tag(tag, tags=None):\n"
                    "    tags = set() if tags is None else set(tags)\n"
                    "    tags.add(tag)\n"
                    "    return sorted(tags)\n"
                ),
                buggy=(
                    "def add_tag(tag, tags=set()):\n"
                    "    tags.add(tag)\n"
                    "    return sorted(tags)\n"
                ),
                cases=[
                    C("m.add_tag('a')"),
                    C("m.add_tag('b')", "m.add_tag('a')"),
                    C("m.add_tag('c')", "m.add_tag('a')", "m.add_tag('b')"),
                ],
            ),
            dict(
                entry="record",
                statement="实现 record(k, v, store=None)：返回写入 k=v 之后的字典；store 缺省时从空字典开始。每次调用互不影响。",
                fixed=(
                    "def record(k, v, store=None):\n"
                    "    store = {} if store is None else dict(store)\n"
                    "    store[k] = v\n"
                    "    return store\n"
                ),
                buggy=(
                    "def record(k, v, store={}):\n"
                    "    store[k] = v\n"
                    "    return store\n"
                ),
                cases=[
                    C("m.record('a', 1)"),
                    C("m.record('b', 2)", "m.record('a', 1)"),
                    C("m.record('a', 9)", "m.record('a', 1)"),
                ],
            ),
            dict(
                entry="count_calls",
                statement="实现 count_calls(name, tally=None)：返回 name 的计数加一之后的字典；tally 缺省时从空字典开始。每次调用互不影响。",
                fixed=(
                    "def count_calls(name, tally=None):\n"
                    "    tally = {} if tally is None else dict(tally)\n"
                    "    tally[name] = tally.get(name, 0) + 1\n"
                    "    return tally\n"
                ),
                buggy=(
                    "def count_calls(name, tally={}):\n"
                    "    tally[name] = tally.get(name, 0) + 1\n"
                    "    return tally\n"
                ),
                cases=[
                    C("m.count_calls('a')"),
                    C("m.count_calls('a')", "m.count_calls('a')"),
                    C("m.count_calls('a')", "m.count_calls('a')", "m.count_calls('b')"),
                ],
            ),
            dict(
                entry="extend_all",
                statement="实现 extend_all(xs, out=None)：返回把 xs 全部元素接到 out 之后的新列表；out 缺省时从空列表开始。每次调用互不影响。",
                fixed=(
                    "def extend_all(xs, out=None):\n"
                    "    out = [] if out is None else list(out)\n"
                    "    out.extend(xs)\n"
                    "    return out\n"
                ),
                buggy=(
                    "def extend_all(xs, out=[]):\n"
                    "    out.extend(xs)\n"
                    "    return out\n"
                ),
                cases=[
                    C("m.extend_all([1, 2])"),
                    C("m.extend_all([3])", "m.extend_all([1, 2])"),
                    C("m.extend_all([9])", "m.extend_all([1])", "m.extend_all([2])"),
                ],
            ),
            dict(
                entry="add_to_log",
                statement="实现 add_to_log(msg)：把 msg 记入模块内的日志，并返回此刻日志的快照。先前返回的快照不得被后续记录改动。",
                fixed=(
                    "_LOG = []\n"
                    "\n"
                    "def add_to_log(msg):\n"
                    "    _LOG.append(msg)\n"
                    "    return list(_LOG)\n"
                ),
                buggy=(
                    "_LOG = []\n"
                    "\n"
                    "def add_to_log(msg):\n"
                    "    _LOG.append(msg)\n"
                    "    return _LOG\n"
                ),
                cases=[
                    C("m.add_to_log('a')"),
                    C("snap", "snap = m.add_to_log('a')", "m.add_to_log('b')"),
                    C("snap", "snap = m.add_to_log('a')", "m.add_to_log('b')", "m.add_to_log('c')"),
                ],
            ),
            dict(
                entry="put",
                statement="实现 put(k, v)：把 k=v 写入模块内的表，并返回此刻表的快照。先前返回的快照不得被后续写入改动。",
                fixed=(
                    "_TABLE = {}\n"
                    "\n"
                    "def put(k, v):\n"
                    "    _TABLE[k] = v\n"
                    "    return dict(_TABLE)\n"
                ),
                buggy=(
                    "_TABLE = {}\n"
                    "\n"
                    "def put(k, v):\n"
                    "    _TABLE[k] = v\n"
                    "    return _TABLE\n"
                ),
                cases=[
                    C("m.put('a', 1)"),
                    C("snap", "snap = m.put('a', 1)", "m.put('b', 2)"),
                    C("snap", "snap = m.put('a', 1)", "m.put('a', 2)"),
                ],
            ),
            dict(
                entry="extend_log",
                statement="实现 extend_log(xs)：把 xs 全部元素记入模块内的日志，并返回此刻日志的快照。先前返回的快照不得被后续记录改动。",
                fixed=(
                    "_LOG = []\n"
                    "\n"
                    "def extend_log(xs):\n"
                    "    _LOG.extend(xs)\n"
                    "    return list(_LOG)\n"
                ),
                buggy=(
                    "_LOG = []\n"
                    "\n"
                    "def extend_log(xs):\n"
                    "    _LOG.extend(xs)\n"
                    "    return _LOG\n"
                ),
                cases=[
                    C("m.extend_log([1, 2])"),
                    C("snap", "snap = m.extend_log([1])", "m.extend_log([2])"),
                    C("snap", "snap = m.extend_log([1])", "m.extend_log([2])", "m.extend_log([3])"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 3
    "strindex": {
        "failure_mode": "字符串索引与切片：索引方向、切分方式、大小写、端点字符",
        "variants": [
            dict(
                entry="first_word",
                statement="实现 first_word(s)：返回 s 的第一个单词；s 为空或只有空白时返回空字符串。单词之间可能隔多个空格。",
                fixed=(
                    "def first_word(s):\n"
                    "    parts = s.split()\n"
                    "    return parts[0] if parts else ''\n"
                ),
                buggy=(
                    "def first_word(s):\n"
                    "    parts = s.split(' ')\n"
                    "    return parts[0] if parts else ''\n"
                ),
                cases=[
                    C("m.first_word('hello world')"),
                    C("m.first_word('   spaced   out')"),
                    C("m.first_word('')"),
                ],
            ),
            dict(
                entry="last_char",
                statement="实现 last_char(s)：返回 s 的最后一个字符；s 为空时返回空字符串。",
                fixed=(
                    "def last_char(s):\n"
                    "    return s[-1] if s else ''\n"
                ),
                buggy=(
                    "def last_char(s):\n"
                    "    return s[1] if len(s) > 1 else ''\n"
                ),
                cases=[
                    C("m.last_char('abc')"),
                    C("m.last_char('a')"),
                    C("m.last_char('')"),
                ],
            ),
            dict(
                entry="without_ends",
                statement="实现 without_ends(s)：去掉 s 的第一个和最后一个字符后返回；长度不足两个时返回空字符串。",
                fixed=(
                    "def without_ends(s):\n"
                    "    return s[1:-1]\n"
                ),
                buggy=(
                    "def without_ends(s):\n"
                    "    return s[:-1]\n"
                ),
                cases=[
                    C("m.without_ends('abcdef')"),
                    C("m.without_ends('ab')"),
                    C("m.without_ends('a')"),
                ],
            ),
            dict(
                entry="title_words",
                statement="实现 title_words(s)：把每个单词改成首字母大写、其余小写，并用单个空格连接。",
                fixed=(
                    "def title_words(s):\n"
                    "    return ' '.join(w.capitalize() for w in s.split())\n"
                ),
                buggy=(
                    "def title_words(s):\n"
                    "    return ' '.join(w.upper() for w in s.split())\n"
                ),
                cases=[
                    C("m.title_words('hello world')"),
                    C("m.title_words('ONE')"),
                    C("m.title_words('a b c')"),
                ],
            ),
            dict(
                entry="starts_with_ci",
                statement="实现 starts_with_ci(s, prefix)：忽略大小写判断 s 是否以 prefix 开头。",
                fixed=(
                    "def starts_with_ci(s, prefix):\n"
                    "    return s.lower().startswith(prefix.lower())\n"
                ),
                buggy=(
                    "def starts_with_ci(s, prefix):\n"
                    "    return s.startswith(prefix)\n"
                ),
                cases=[
                    C("m.starts_with_ci('Hello', 'he')"),
                    C("m.starts_with_ci('Hello', 'He')"),
                    C("m.starts_with_ci('Hi', 'hI')"),
                ],
            ),
            dict(
                entry="count_char",
                statement="实现 count_char(s, ch)：区分大小写地统计 ch 在 s 中出现的次数。",
                fixed=(
                    "def count_char(s, ch):\n"
                    "    return s.count(ch)\n"
                ),
                buggy=(
                    "def count_char(s, ch):\n"
                    "    return s.count(ch.lower())\n"
                ),
                cases=[
                    C("m.count_char('Banana', 'a')"),
                    C("m.count_char('Banana', 'A')"),
                    C("m.count_char('AaA', 'A')"),
                ],
            ),
            dict(
                entry="reverse_words",
                statement="实现 reverse_words(s)：把 s 中的单词顺序颠倒，单词之间用单个空格连接。",
                fixed=(
                    "def reverse_words(s):\n"
                    "    return ' '.join(reversed(s.split()))\n"
                ),
                buggy=(
                    "def reverse_words(s):\n"
                    "    return ' '.join(reversed(list(s)))\n"
                ),
                cases=[
                    C("m.reverse_words('one two')"),
                    C("m.reverse_words('a b')"),
                    C("m.reverse_words('x')"),
                ],
            ),
            dict(
                entry="strip_punct",
                statement="实现 strip_punct(s)：去掉 s 首尾的标点符号（英文句号、逗号、感叹号、问号），其余部分原样保留。",
                fixed=(
                    "def strip_punct(s):\n"
                    "    return s.strip('.,!?')\n"
                ),
                buggy=(
                    "def strip_punct(s):\n"
                    "    return s.strip('.!?')\n"
                ),
                cases=[
                    C("m.strip_punct('hello,')"),
                    C("m.strip_punct('hi!')"),
                    C("m.strip_punct('a,b')"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 4
    "dictmiss": {
        "failure_mode": "缺失键与计数初始化：默认值语义、累加被覆盖、缺失路径的返回",
        "variants": [
            dict(
                entry="word_count",
                statement="实现 word_count(words)：返回每个词出现次数的字典。",
                fixed=(
                    "def word_count(words):\n"
                    "    d = {}\n"
                    "    for w in words:\n"
                    "        d[w] = d.get(w, 0) + 1\n"
                    "    return d\n"
                ),
                buggy=(
                    "def word_count(words):\n"
                    "    d = {}\n"
                    "    for w in words:\n"
                    "        d[w] = 1\n"
                    "    return d\n"
                ),
                cases=[
                    C("m.word_count(['a', 'b', 'a'])"),
                    C("m.word_count(['a', 'a', 'a'])"),
                    C("m.word_count([])"),
                ],
            ),
            dict(
                entry="group_by_len",
                statement="实现 group_by_len(words)：按单词长度分组，返回 {长度: [该长度的全部单词]}，组内保持原顺序。",
                fixed=(
                    "def group_by_len(words):\n"
                    "    d = {}\n"
                    "    for w in words:\n"
                    "        d.setdefault(len(w), []).append(w)\n"
                    "    return d\n"
                ),
                buggy=(
                    "def group_by_len(words):\n"
                    "    d = {}\n"
                    "    for w in words:\n"
                    "        d[len(w)] = [w]\n"
                    "    return d\n"
                ),
                cases=[
                    C("m.group_by_len(['a', 'bb', 'cc'])"),
                    C("m.group_by_len(['x', 'y'])"),
                    C("m.group_by_len([])"),
                ],
            ),
            dict(
                entry="get_or",
                statement="实现 get_or(d, k, default)：键存在时返回对应的值（即使该值是 None），否则返回 default。",
                fixed=(
                    "def get_or(d, k, default):\n"
                    "    return d[k] if k in d else default\n"
                ),
                buggy=(
                    "def get_or(d, k, default):\n"
                    "    return d.get(k)\n"
                ),
                cases=[
                    C("m.get_or({'a': 1}, 'a', 0)"),
                    C("m.get_or({}, 'a', 0)"),
                    C("m.get_or({'a': None}, 'a', 0)"),
                ],
            ),
            dict(
                entry="merge_counts",
                statement="实现 merge_counts(a, b)：合并两个计数字典，共同键的计数相加。",
                fixed=(
                    "def merge_counts(a, b):\n"
                    "    out = dict(a)\n"
                    "    for k, v in b.items():\n"
                    "        out[k] = out.get(k, 0) + v\n"
                    "    return out\n"
                ),
                buggy=(
                    "def merge_counts(a, b):\n"
                    "    out = dict(a)\n"
                    "    out.update(b)\n"
                    "    return out\n"
                ),
                cases=[
                    C("m.merge_counts({'a': 1}, {'a': 2})"),
                    C("m.merge_counts({'a': 2, 'b': 1}, {'b': 3})"),
                    C("m.merge_counts({'a': 1}, {'b': 1})"),
                ],
            ),
            dict(
                entry="invert",
                statement="实现 invert(d)：把键值互换，相同值对应的多个键收集成列表，返回 {原值: [原键列表]}。",
                fixed=(
                    "def invert(d):\n"
                    "    out = {}\n"
                    "    for k, v in d.items():\n"
                    "        out.setdefault(v, []).append(k)\n"
                    "    return out\n"
                ),
                buggy=(
                    "def invert(d):\n"
                    "    out = {}\n"
                    "    for k, v in d.items():\n"
                    "        out[v] = k\n"
                    "    return out\n"
                ),
                cases=[
                    C("m.invert({'a': 1, 'b': 2})"),
                    C("m.invert({'a': 1, 'b': 1})"),
                    C("m.invert({})"),
                ],
            ),
            dict(
                entry="tally_add",
                statement="实现 tally_add(tally, k, n)：在原计数字典上把 k 的计数增加 n，并返回该字典。",
                fixed=(
                    "def tally_add(tally, k, n):\n"
                    "    tally[k] = tally.get(k, 0) + n\n"
                    "    return tally\n"
                ),
                buggy=(
                    "def tally_add(tally, k, n):\n"
                    "    tally[k] = n\n"
                    "    return tally\n"
                ),
                cases=[
                    C("m.tally_add(t, 'a', 2)", "t = {'a': 1}"),
                    C("m.tally_add(t, 'b', 5)", "t = {'b': 1}"),
                    C("m.tally_add(t, 'c', 3)", "t = {}"),
                ],
            ),
            dict(
                entry="lookup",
                statement="实现 lookup(d, path, default)：沿 path 中的键逐层进入嵌套字典，任一层缺失就返回 default，存在则返回最终值。",
                fixed=(
                    "def lookup(d, path, default=None):\n"
                    "    cur = d\n"
                    "    for p in path:\n"
                    "        if not isinstance(cur, dict) or p not in cur:\n"
                    "            return default\n"
                    "        cur = cur[p]\n"
                    "    return cur\n"
                ),
                buggy=(
                    "def lookup(d, path, default=None):\n"
                    "    cur = d\n"
                    "    for p in path:\n"
                    "        cur = cur.get(p)\n"
                    "        if cur is None:\n"
                    "            break\n"
                    "    return cur\n"
                ),
                cases=[
                    C("m.lookup({'a': {'b': 7}}, ['a', 'b'], 'MISS')"),
                    C("m.lookup({'a': {'b': 7}}, ['a', 'z'], 'MISS')"),
                    C("m.lookup({'a': {'b': 7}}, ['x'], 'MISS')"),
                ],
            ),
            dict(
                entry="char_positions",
                statement="实现 char_positions(s)：返回每个字符出现位置的字典，值为该字符全部下标的列表。",
                fixed=(
                    "def char_positions(s):\n"
                    "    out = {}\n"
                    "    for i, ch in enumerate(s):\n"
                    "        out.setdefault(ch, []).append(i)\n"
                    "    return out\n"
                ),
                buggy=(
                    "def char_positions(s):\n"
                    "    out = {}\n"
                    "    for i, ch in enumerate(s):\n"
                    "        out[ch] = i\n"
                    "    return out\n"
                ),
                cases=[
                    C("m.char_positions('aba')"),
                    C("m.char_positions('aab')"),
                    C("m.char_positions('')"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 5
    "sortkey": {
        "failure_mode": "排序键与稳定性：键取错字段、缺次级键、反向用错位置",
        "variants": [
            dict(
                entry="sort_by_len",
                statement="实现 sort_by_len(words)：按单词长度升序排列，长度相同的保持原顺序。",
                fixed=(
                    "def sort_by_len(words):\n"
                    "    return sorted(words, key=len)\n"
                ),
                buggy=(
                    "def sort_by_len(words):\n"
                    "    return sorted(words, reverse=True)\n"
                ),
                cases=[
                    C("m.sort_by_len(['ccc', 'a', 'bb'])"),
                    C("m.sort_by_len(['b', 'a'])"),
                    C("m.sort_by_len([])"),
                ],
            ),
            dict(
                entry="sort_by_second",
                statement="实现 sort_by_second(pairs)：按每个二元组的第二个元素升序排列。",
                fixed=(
                    "def sort_by_second(pairs):\n"
                    "    return sorted(pairs, key=lambda p: p[1])\n"
                ),
                buggy=(
                    "def sort_by_second(pairs):\n"
                    "    return sorted(pairs, key=lambda p: p[0])\n"
                ),
                cases=[
                    C("m.sort_by_second([(1, 3), (2, 1)])"),
                    C("m.sort_by_second([(5, 2), (1, 9)])"),
                    C("m.sort_by_second([])"),
                ],
            ),
            dict(
                entry="top_n",
                statement="实现 top_n(xs, n)：返回 xs 中最大的 n 个数，按从大到小排列。",
                fixed=(
                    "def top_n(xs, n):\n"
                    "    return sorted(xs, reverse=True)[:n]\n"
                ),
                buggy=(
                    "def top_n(xs, n):\n"
                    "    return sorted(xs)[:n]\n"
                ),
                cases=[
                    C("m.top_n([3, 1, 2], 2)"),
                    C("m.top_n([10, 20, 30], 3)"),
                    C("m.top_n([5], 1)"),
                ],
            ),
            dict(
                entry="sort_by_len_then_alpha",
                statement="实现 sort_by_len_then_alpha(words)：先按长度升序，长度相同再按字典序升序。",
                fixed=(
                    "def sort_by_len_then_alpha(words):\n"
                    "    return sorted(words, key=lambda w: (len(w), w))\n"
                ),
                buggy=(
                    "def sort_by_len_then_alpha(words):\n"
                    "    return sorted(words, key=lambda w: (w, len(w)))\n"
                ),
                cases=[
                    C("m.sort_by_len_then_alpha(['b', 'aa', 'c'])"),
                    C("m.sort_by_len_then_alpha(['bb', 'b', 'a'])"),
                    C("m.sort_by_len_then_alpha([])"),
                ],
            ),
            dict(
                entry="sort_abs",
                statement="实现 sort_abs(xs)：按绝对值升序排列。",
                fixed=(
                    "def sort_abs(xs):\n"
                    "    return sorted(xs, key=abs)\n"
                ),
                buggy=(
                    "def sort_abs(xs):\n"
                    "    return sorted(xs)\n"
                ),
                cases=[
                    C("m.sort_abs([-5, 3, -1])"),
                    C("m.sort_abs([2, -2])"),
                    C("m.sort_abs([])"),
                ],
            ),
            dict(
                entry="sort_by_value",
                statement="实现 sort_by_value(d)：返回键的列表，按对应的值升序排列，值相同再按键升序。",
                fixed=(
                    "def sort_by_value(d):\n"
                    "    return sorted(d, key=lambda k: (d[k], k))\n"
                ),
                buggy=(
                    "def sort_by_value(d):\n"
                    "    return sorted(d)\n"
                ),
                cases=[
                    C("m.sort_by_value({'b': 1, 'a': 2})"),
                    C("m.sort_by_value({'c': 1, 'a': 2, 'b': 3})"),
                    C("m.sort_by_value({'a': 1, 'b': 1})"),
                ],
            ),
            dict(
                entry="sort_desc_stable",
                statement="实现 sort_desc_stable(words)：按长度降序排列，长度相同的保持原顺序（稳定）。",
                fixed=(
                    "def sort_desc_stable(words):\n"
                    "    return sorted(words, key=len, reverse=True)\n"
                ),
                buggy=(
                    "def sort_desc_stable(words):\n"
                    "    return sorted(words, reverse=True)\n"
                ),
                cases=[
                    C("m.sort_desc_stable(['b', 'aa', 'c'])"),
                    C("m.sort_desc_stable(['aa', 'b', 'cc'])"),
                    C("m.sort_desc_stable([])"),
                ],
            ),
            dict(
                entry="argmax_by",
                statement="实现 argmax_by(xs, key)：返回使 key(x) 最大的那个元素。",
                fixed=(
                    "def argmax_by(xs, key):\n"
                    "    return max(xs, key=key)\n"
                ),
                buggy=(
                    "def argmax_by(xs, key):\n"
                    "    return max(xs)\n"
                ),
                cases=[
                    C("m.argmax_by(['b', 'aa', 'c'], len)"),
                    C("m.argmax_by([1, -5, 3], abs)"),
                    C("m.argmax_by(['x'], len)"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 6
    "errorcontract": {
        "failure_mode": "输入契约：非法或越界输入应当返回什么，而不是抛什么",
        "variants": [
            dict(
                entry="safe_div",
                statement="实现 safe_div(a, b)：返回 a 除以 b 的浮点数；b 为 0 时返回 None。不抛异常。",
                fixed=(
                    "def safe_div(a, b):\n"
                    "    if b == 0:\n"
                    "        return None\n"
                    "    return a / b\n"
                ),
                buggy=(
                    "def safe_div(a, b):\n"
                    "    if b == 0:\n"
                    "        return 0.0\n"
                    "    return a / b\n"
                ),
                cases=[
                    C("m.safe_div(6, 3)"),
                    C("m.safe_div(6, 0)"),
                    C("m.safe_div(0, 5)"),
                ],
            ),
            dict(
                entry="parse_int",
                statement="实现 parse_int(s, default=None)：把 s 转成整数；无法转换时返回 default。不抛异常。",
                fixed=(
                    "def parse_int(s, default=None):\n"
                    "    try:\n"
                    "        return int(s)\n"
                    "    except (TypeError, ValueError):\n"
                    "        return default\n"
                ),
                buggy=(
                    "def parse_int(s, default=None):\n"
                    "    try:\n"
                    "        return int(s)\n"
                    "    except (TypeError, ValueError):\n"
                    "        return 0\n"
                ),
                cases=[
                    C("m.parse_int('12')"),
                    C("m.parse_int('x', -1)"),
                    C("m.parse_int('3.5', None)"),
                ],
            ),
            dict(
                entry="at_or",
                statement="实现 at_or(xs, i, default=None)：返回下标 i 处的元素；i 越界或 xs 为空时返回 default。不抛异常。",
                fixed=(
                    "def at_or(xs, i, default=None):\n"
                    "    if not xs or i < -len(xs) or i >= len(xs):\n"
                    "        return default\n"
                    "    return xs[i]\n"
                ),
                buggy=(
                    "def at_or(xs, i, default=None):\n"
                    "    if not xs:\n"
                    "        return default\n"
                    "    return xs[i] if -len(xs) <= i < len(xs) else xs[-1]\n"
                ),
                cases=[
                    C("m.at_or([1, 2, 3], 1)"),
                    C("m.at_or([1, 2, 3], 9, 'X')"),
                    C("m.at_or([], 0, 'X')"),
                ],
            ),
            dict(
                entry="normalize_score",
                statement="实现 normalize_score(v)：v 是 0 到 100 之间的数（含端点）时返回它的浮点数；不是数值类型，或超出该区间时返回 None。不抛异常。",
                fixed=(
                    "def normalize_score(v):\n"
                    "    if isinstance(v, bool) or not isinstance(v, (int, float)):\n"
                    "        return None\n"
                    "    if v < 0 or v > 100:\n"
                    "        return None\n"
                    "    return float(v)\n"
                ),
                buggy=(
                    "def normalize_score(v):\n"
                    "    return float(min(max(v, 0), 100))\n"
                ),
                cases=[
                    C("m.normalize_score(50)"),
                    C("m.normalize_score(-5)"),
                    C("m.normalize_score(150)"),
                ],
            ),
            dict(
                entry="first_or",
                statement="实现 first_or(xs, default=None)：返回第一个元素；xs 为空时返回 default（default 可以是任何值，包括 None）。",
                fixed=(
                    "def first_or(xs, default=None):\n"
                    "    return xs[0] if xs else default\n"
                ),
                buggy=(
                    "def first_or(xs, default=None):\n"
                    "    return xs[0] if xs else None\n"
                ),
                cases=[
                    C("m.first_or([1, 2])"),
                    C("m.first_or([], 'X')"),
                    C("m.first_or([], None)"),
                ],
            ),
            dict(
                entry="max_or",
                statement="实现 max_or(xs, default=None)：返回最大值；xs 为空时返回 default（default 可以是任何值）。",
                fixed=(
                    "def max_or(xs, default=None):\n"
                    "    return max(xs) if xs else default\n"
                ),
                buggy=(
                    "def max_or(xs, default=None):\n"
                    "    return max(xs) if xs else 0\n"
                ),
                cases=[
                    C("m.max_or([1, 5])"),
                    C("m.max_or([], 'X')"),
                    C("m.max_or([-3])"),
                ],
            ),
            dict(
                entry="join_nonempty",
                statement="实现 join_nonempty(parts, sep)：用 sep 连接 parts，跳过其中的空字符串。",
                fixed=(
                    "def join_nonempty(parts, sep):\n"
                    "    return sep.join(p for p in parts if p != '')\n"
                ),
                buggy=(
                    "def join_nonempty(parts, sep):\n"
                    "    return sep.join(parts)\n"
                ),
                cases=[
                    C("m.join_nonempty(['a', '', 'b'], '-')"),
                    C("m.join_nonempty(['a', '', '', 'b'], '-')"),
                    C("m.join_nonempty(['a', 'b'], '-')"),
                ],
            ),
            dict(
                entry="safe_index",
                statement="实现 safe_index(xs, v)：返回 v 在 xs 中第一次出现的下标；不存在时返回 -1。不抛异常。",
                fixed=(
                    "def safe_index(xs, v):\n"
                    "    return xs.index(v) if v in xs else -1\n"
                ),
                buggy=(
                    "def safe_index(xs, v):\n"
                    "    return xs.index(v) if v in xs else len(xs)\n"
                ),
                cases=[
                    C("m.safe_index([1, 2], 2)"),
                    C("m.safe_index([1, 2], 9)"),
                    C("m.safe_index([], 9)"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 7
    "classstate": {
        "failure_mode": "对象状态累积：实例属性与类属性混淆、状态未更新、副作用与返回值不一致",
        "variants": [
            dict(
                entry="Counter",
                statement="实现 Counter 类：初始 total 为 0；add(n) 把 n 累加到 total 并返回累加后的 total。",
                fixed=(
                    "class Counter:\n"
                    "    def __init__(self):\n"
                    "        self.total = 0\n"
                    "\n"
                    "    def add(self, n):\n"
                    "        self.total += n\n"
                    "        return self.total\n"
                ),
                buggy=(
                    "class Counter:\n"
                    "    def __init__(self):\n"
                    "        self.total = 0\n"
                    "\n"
                    "    def add(self, n):\n"
                    "        self.total = n\n"
                    "        return self.total\n"
                ),
                cases=[
                    C("c.add(3)", "c = m.Counter()"),
                    C("c.add(4)", "c = m.Counter()", "c.add(3)"),
                    C("c.add(3)", "c = m.Counter()", "c.add(1)", "c.add(2)"),
                ],
            ),
            dict(
                entry="Stack",
                statement="实现 Stack 类：push(x) 把 x 压入，pop() 弹出并返回栈顶，栈空时返回 None；items 是当前栈内容（栈底在前）。",
                fixed=(
                    "class Stack:\n"
                    "    def __init__(self):\n"
                    "        self.items = []\n"
                    "\n"
                    "    def push(self, x):\n"
                    "        self.items.append(x)\n"
                    "\n"
                    "    def pop(self):\n"
                    "        return self.items.pop() if self.items else None\n"
                ),
                buggy=(
                    "class Stack:\n"
                    "    def __init__(self):\n"
                    "        self.items = []\n"
                    "\n"
                    "    def push(self, x):\n"
                    "        self.items.append(x)\n"
                    "\n"
                    "    def pop(self):\n"
                    "        return self.items[-1] if self.items else None\n"
                ),
                cases=[
                    C("s.pop()", "s = m.Stack()", "s.push(1)", "s.push(2)"),
                    C("s.items", "s = m.Stack()", "s.push(1)", "s.push(2)", "s.pop()"),
                    C("s.pop()", "s = m.Stack()"),
                ],
            ),
            dict(
                entry="BankAccount",
                statement="实现 BankAccount 类：每个账户有独立的 balance，初始为 0；deposit(n) 把 n 存入该账户并返回存入后的余额。",
                fixed=(
                    "class BankAccount:\n"
                    "    def __init__(self):\n"
                    "        self.balance = 0\n"
                    "\n"
                    "    def deposit(self, n):\n"
                    "        self.balance += n\n"
                    "        return self.balance\n"
                ),
                buggy=(
                    "class BankAccount:\n"
                    "    balance = 0\n"
                    "\n"
                    "    def __init__(self):\n"
                    "        pass\n"
                    "\n"
                    "    def deposit(self, n):\n"
                    "        BankAccount.balance += n\n"
                    "        return self.balance\n"
                ),
                cases=[
                    C("b.deposit(5)", "a = m.BankAccount()", "a.deposit(10)", "b = m.BankAccount()"),
                    C("a.balance", "a = m.BankAccount()", "b = m.BankAccount()", "a.deposit(1)", "b.deposit(2)"),
                    C("a.deposit(10)", "a = m.BankAccount()"),
                ],
            ),
            dict(
                entry="Toggle",
                statement="实现 Toggle 类：state 初始为 False；flip() 把 state 取反，保存，并返回取反后的值。",
                fixed=(
                    "class Toggle:\n"
                    "    def __init__(self):\n"
                    "        self.state = False\n"
                    "\n"
                    "    def flip(self):\n"
                    "        self.state = not self.state\n"
                    "        return self.state\n"
                ),
                buggy=(
                    "class Toggle:\n"
                    "    def __init__(self):\n"
                    "        self.state = False\n"
                    "\n"
                    "    def flip(self):\n"
                    "        return not self.state\n"
                ),
                cases=[
                    C("t.flip()", "t = m.Toggle()"),
                    C("t.flip()", "t = m.Toggle()", "t.flip()"),
                    C("t.state", "t = m.Toggle()", "t.flip()", "t.flip()", "t.flip()"),
                ],
            ),
            dict(
                entry="Averager",
                statement="实现 Averager 类：add(x) 记录 x 并返回到目前为止所有已加入数值的平均值。",
                fixed=(
                    "class Averager:\n"
                    "    def __init__(self):\n"
                    "        self._sum = 0\n"
                    "        self._n = 0\n"
                    "\n"
                    "    def add(self, x):\n"
                    "        self._sum += x\n"
                    "        self._n += 1\n"
                    "        return self._sum / self._n\n"
                ),
                buggy=(
                    "class Averager:\n"
                    "    def __init__(self):\n"
                    "        self._sum = 0\n"
                    "        self._n = 0\n"
                    "\n"
                    "    def add(self, x):\n"
                    "        self._sum += x\n"
                    "        self._n += 2\n"
                    "        return self._sum / self._n\n"
                ),
                cases=[
                    C("a.add(2)", "a = m.Averager()"),
                    C("a.add(4)", "a = m.Averager()", "a.add(2)"),
                    C("a.add(3)", "a = m.Averager()", "a.add(1)", "a.add(2)"),
                ],
            ),
            dict(
                entry="UniqueQueue",
                statement="实现 UniqueQueue 类：add(x) 只有在 x 从未加入过时才把它加入队尾，并返回当前队列的列表副本。",
                fixed=(
                    "class UniqueQueue:\n"
                    "    def __init__(self):\n"
                    "        self._seen = set()\n"
                    "        self.items = []\n"
                    "\n"
                    "    def add(self, x):\n"
                    "        if x not in self._seen:\n"
                    "            self._seen.add(x)\n"
                    "            self.items.append(x)\n"
                    "        return list(self.items)\n"
                ),
                buggy=(
                    "class UniqueQueue:\n"
                    "    def __init__(self):\n"
                    "        self.items = []\n"
                    "\n"
                    "    def add(self, x):\n"
                    "        self.items.append(x)\n"
                    "        return list(self.items)\n"
                ),
                cases=[
                    C("u.add(1)", "u = m.UniqueQueue()"),
                    C("u.add(1)", "u = m.UniqueQueue()", "u.add(1)"),
                    C("u.add(1)", "u = m.UniqueQueue()", "u.add(1)", "u.add(2)"),
                ],
            ),
            dict(
                entry="Buffer",
                statement="实现 Buffer 类：构造时给定容量 cap；put(x) 加入 x，若加入后长度超过 cap 就丢弃最早的元素，返回当前内容的列表副本。",
                fixed=(
                    "class Buffer:\n"
                    "    def __init__(self, cap):\n"
                    "        self.cap = cap\n"
                    "        self.items = []\n"
                    "\n"
                    "    def put(self, x):\n"
                    "        if len(self.items) >= self.cap:\n"
                    "            self.items.pop(0)\n"
                    "        self.items.append(x)\n"
                    "        return list(self.items)\n"
                ),
                buggy=(
                    "class Buffer:\n"
                    "    def __init__(self, cap):\n"
                    "        self.cap = cap\n"
                    "        self.items = []\n"
                    "\n"
                    "    def put(self, x):\n"
                    "        if len(self.items) > self.cap:\n"
                    "            self.items.pop(0)\n"
                    "        self.items.append(x)\n"
                    "        return list(self.items)\n"
                ),
                cases=[
                    C("b.put(1)", "b = m.Buffer(2)"),
                    C("b.put(3)", "b = m.Buffer(2)", "b.put(1)", "b.put(2)"),
                    C("b.put(4)", "b = m.Buffer(2)", "b.put(1)", "b.put(2)", "b.put(3)"),
                ],
            ),
            dict(
                entry="Tally",
                statement="实现 Tally 类：bump(k) 把 k 的计数加一并返回计数字典的副本；reset() 清空全部计数并返回清空后的字典副本。",
                fixed=(
                    "class Tally:\n"
                    "    def __init__(self):\n"
                    "        self.counts = {}\n"
                    "\n"
                    "    def bump(self, k):\n"
                    "        self.counts[k] = self.counts.get(k, 0) + 1\n"
                    "        return dict(self.counts)\n"
                    "\n"
                    "    def reset(self):\n"
                    "        self.counts = {}\n"
                    "        return dict(self.counts)\n"
                ),
                buggy=(
                    "class Tally:\n"
                    "    def __init__(self):\n"
                    "        self.counts = {}\n"
                    "\n"
                    "    def bump(self, k):\n"
                    "        self.counts[k] = self.counts.get(k, 0) + 1\n"
                    "        return dict(self.counts)\n"
                    "\n"
                    "    def reset(self):\n"
                    "        return dict(self.counts)\n"
                ),
                cases=[
                    C("t.bump('a')", "t = m.Tally()"),
                    C("t.reset()", "t = m.Tally()", "t.bump('a')"),
                    C("t.bump('b')", "t = m.Tally()", "t.bump('a')", "t.reset()"),
                ],
            ),
        ],
    },
    # ------------------------------------------------------------------ 8
    "recursionbase": {
        "failure_mode": "递归基例与终止：基线取值、递归参数不收敛、嵌套未展开",
        "variants": [
            dict(
                entry="fact",
                statement="实现 fact(n)：返回 n 的阶乘，递归实现。0 的阶乘是 1。",
                fixed=(
                    "def fact(n):\n"
                    "    if n <= 1:\n"
                    "        return 1\n"
                    "    return n * fact(n - 1)\n"
                ),
                buggy=(
                    "def fact(n):\n"
                    "    if n <= 1:\n"
                    "        return 0\n"
                    "    return n * fact(n - 1)\n"
                ),
                cases=[
                    C("m.fact(0)"),
                    C("m.fact(5)"),
                    C("m.fact(1)"),
                ],
            ),
            dict(
                entry="fib",
                statement="实现 fib(n)：返回第 n 个斐波那契数，递归实现。fib(0)=0，fib(1)=1。",
                fixed=(
                    "def fib(n):\n"
                    "    if n < 2:\n"
                    "        return n\n"
                    "    return fib(n - 1) + fib(n - 2)\n"
                ),
                buggy=(
                    "def fib(n):\n"
                    "    if n < 2:\n"
                    "        return 1\n"
                    "    return fib(n - 1) + fib(n - 2)\n"
                ),
                cases=[
                    C("m.fib(0)"),
                    C("m.fib(6)"),
                    C("m.fib(1)"),
                ],
            ),
            dict(
                entry="sum_list",
                statement="实现 sum_list(xs)：用递归返回列表所有元素之和，空列表返回 0。",
                fixed=(
                    "def sum_list(xs):\n"
                    "    if not xs:\n"
                    "        return 0\n"
                    "    return xs[0] + sum_list(xs[1:])\n"
                ),
                buggy=(
                    "def sum_list(xs):\n"
                    "    if len(xs) <= 1:\n"
                    "        return 0\n"
                    "    return xs[0] + sum_list(xs[1:])\n"
                ),
                cases=[
                    C("m.sum_list([1, 2, 3])"),
                    C("m.sum_list([5])"),
                    C("m.sum_list([])"),
                ],
            ),
            dict(
                entry="count_down",
                statement="实现 count_down(n)：递归返回 [n, n-1, ..., 1]；n 不大于 0 时返回空列表。",
                fixed=(
                    "def count_down(n):\n"
                    "    if n <= 0:\n"
                    "        return []\n"
                    "    return [n] + count_down(n - 1)\n"
                ),
                buggy=(
                    "def count_down(n):\n"
                    "    if n <= 1:\n"
                    "        return []\n"
                    "    return [n] + count_down(n - 1)\n"
                ),
                cases=[
                    C("m.count_down(3)"),
                    C("m.count_down(1)"),
                    C("m.count_down(0)"),
                ],
            ),
            dict(
                entry="gcd",
                statement="实现 gcd(a, b)：用欧几里得算法递归返回最大公约数；b 为 0 时返回 a。",
                fixed=(
                    "def gcd(a, b):\n"
                    "    if b == 0:\n"
                    "        return a\n"
                    "    return gcd(b, a % b)\n"
                ),
                buggy=(
                    "def gcd(a, b):\n"
                    "    if b == 0:\n"
                    "        return b\n"
                    "    return gcd(b, a % b)\n"
                ),
                cases=[
                    C("m.gcd(12, 8)"),
                    C("m.gcd(7, 0)"),
                    C("m.gcd(6, 6)"),
                ],
            ),
            dict(
                entry="power",
                statement="实现 power(b, e)：递归返回 b 的 e 次幂；e 为 0 时返回 1。",
                fixed=(
                    "def power(b, e):\n"
                    "    if e == 0:\n"
                    "        return 1\n"
                    "    return b * power(b, e - 1)\n"
                ),
                buggy=(
                    "def power(b, e):\n"
                    "    if e == 0:\n"
                    "        return 0\n"
                    "    return b * power(b, e - 1)\n"
                ),
                cases=[
                    C("m.power(2, 3)"),
                    C("m.power(5, 0)"),
                    C("m.power(2, 1)"),
                ],
            ),
            dict(
                entry="flatten",
                statement="实现 flatten(xs)：把任意深度嵌套的列表摊平成一维列表，非列表元素原样保留。",
                fixed=(
                    "def flatten(xs):\n"
                    "    out = []\n"
                    "    for x in xs:\n"
                    "        if isinstance(x, list):\n"
                    "            out.extend(flatten(x))\n"
                    "        else:\n"
                    "            out.append(x)\n"
                    "    return out\n"
                ),
                buggy=(
                    "def flatten(xs):\n"
                    "    out = []\n"
                    "    for x in xs:\n"
                    "        out.append(x)\n"
                    "    return out\n"
                ),
                cases=[
                    C("m.flatten([1, [2, 3]])"),
                    C("m.flatten([[1], [2]])"),
                    C("m.flatten([])"),
                ],
            ),
            dict(
                entry="depth",
                statement="实现 depth(xs)：返回嵌套列表的最大深度。非列表为 0，空列表为 1，[1,[2]] 为 2。",
                fixed=(
                    "def depth(xs):\n"
                    "    if not isinstance(xs, list):\n"
                    "        return 0\n"
                    "    if not xs:\n"
                    "        return 1\n"
                    "    return 1 + max(depth(x) for x in xs)\n"
                ),
                buggy=(
                    "def depth(xs):\n"
                    "    if not isinstance(xs, list):\n"
                    "        return 0\n"
                    "    return 1\n"
                ),
                cases=[
                    C("m.depth([1, [2, [3]]])"),
                    C("m.depth([[1], [2]])"),
                    C("m.depth([])"),
                ],
            ),
        ],
    },
}
