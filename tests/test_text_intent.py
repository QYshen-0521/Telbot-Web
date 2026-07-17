from telbot.text_intent import _try_goto_star, normalize_ephemeris_target, parse_intent_zh


def test_normalize_ephemeris_moon_cn() -> None:
    assert normalize_ephemeris_target("月球") == "moon"


def test_parse_describe_intro_jupiter() -> None:
    v = parse_intent_zh("帮我介绍一下木星")
    assert v is not None
    assert v.action == "describe"
    assert v.target == "jupiter"


def test_parse_describe_what_is_m31() -> None:
    v = parse_intent_zh("M31是什么天体")
    assert v is not None
    assert v.action == "describe"
    assert v.target == "M31"


def test_parse_jupiter() -> None:
    v = parse_intent_zh("我要看木星")
    assert v is not None
    assert v.action == "goto"
    assert v.target == "jupiter"


def test_parse_abort() -> None:
    v = parse_intent_zh("立刻停止")
    assert v is not None
    assert v.action == "abort"


def test_parse_abort_short() -> None:
    v = parse_intent_zh("立刻停")
    assert v is not None
    assert v.action == "abort"


def test_parse_park() -> None:
    v = parse_intent_zh("归位")
    assert v is not None
    assert v.action == "park"


def test_parse_connect_english() -> None:
    v = parse_intent_zh("connect")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_zh() -> None:
    v = parse_intent_zh("请连接望远镜")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_lian_shang() -> None:
    v = parse_intent_zh("连上望远镜")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_jian_li() -> None:
    v = parse_intent_zh("建立连接")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_english_mount() -> None:
    v = parse_intent_zh("connect the mount")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_indi_connect() -> None:
    v = parse_intent_zh("indi connect please")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_bare_zh() -> None:
    v = parse_intent_zh("连接")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_whitespace_asr() -> None:
    v = parse_intent_zh("连 接")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_qing_bang() -> None:
    v = parse_intent_zh("请帮我连接")
    assert v is not None
    assert v.action == "connect"


def test_parse_connect_not_duan_kai() -> None:
    """「断开连接」勿判为 connect。"""
    v = parse_intent_zh("断开连接")
    assert v is None or v.action != "connect"


def test_parse_connect_not_wang_luo() -> None:
    v = parse_intent_zh("网络连接")
    assert v is None or v.action != "connect"


def test_parse_unpark_before_park_substring() -> None:
    """「解除停车」含「停车」子串，须识别为 unpark 而非 park。"""
    v = parse_intent_zh("解除停车")
    assert v is not None
    assert v.action == "unpark"


def test_parse_unpark_english() -> None:
    v = parse_intent_zh("unpark")
    assert v is not None
    assert v.action == "unpark"


def test_parse_platesolve_jiaozhun() -> None:
    v = parse_intent_zh("校准")
    assert v is not None
    assert v.action == "platesolve"


def test_parse_platesolve_with_exposure() -> None:
    v = parse_intent_zh("校准拍5秒")
    assert v is not None
    assert v.action == "platesolve"
    assert v.exposure_seconds == 5.0


def test_parse_platesolve_english() -> None:
    v = parse_intent_zh("do a plate solve now")
    assert v is not None
    assert v.action == "platesolve"


def test_parse_platesolve_sync_telescope_phrase() -> None:
    v = parse_intent_zh("校准并同步望远镜")
    assert v is not None
    assert v.action == "platesolve"
    assert v.platesolve_align == "sync"


def test_parse_platesolve_english_sync() -> None:
    v = parse_intent_zh("plate solve and sync please")
    assert v is not None
    assert v.action == "platesolve"
    assert v.platesolve_align == "sync"


def test_parse_snap_phrase() -> None:
    v = parse_intent_zh("拍照")
    assert v is not None
    assert v.action == "snap"
    assert v.exposure_seconds is None


def test_parse_snap_seconds() -> None:
    v = parse_intent_zh("拍5秒")
    assert v is not None
    assert v.action == "snap"
    assert v.exposure_seconds == 5.0


def test_parse_snap_not_when_goto_body_same_sentence() -> None:
    """含「看/指向」与天体时，不以句中「曝光N秒」误盖过 GOTO。"""
    v = parse_intent_zh("看木星曝光3秒")
    assert v is not None
    assert v.action == "goto"
    assert v.target == "jupiter"


def test_parse_unpark_asr_on_park() -> None:
    """Whisper 等常把 unpark 转写成 on park。"""
    for s in ("on park", "on park。", "ON PARK", "onpark", "un park"):
        v = parse_intent_zh(s)
        assert v is not None, s
        assert v.action == "unpark", s


def test_parse_unknown_long() -> None:
    """Avoid false goto on casual mention of a planet."""
    v = parse_intent_zh("今天新闻说火星探测器发射了")
    assert v is None


def test_parse_focuser_position() -> None:
    v = parse_intent_zh("查询当前电调位置")
    assert v is not None
    assert v.action == "focuser_position"


def test_parse_focuser_rel_forward() -> None:
    v = parse_intent_zh("把电调向前移动50")
    assert v is not None
    assert v.action == "focuser_rel"
    assert v.focuser_direction == "out"
    assert v.focuser_steps == 50


def test_parse_focuser_rel_backward() -> None:
    v = parse_intent_zh("电调向后移动100步")
    assert v is not None
    assert v.action == "focuser_rel"
    assert v.focuser_direction == "in"
    assert v.focuser_steps == 100


def test_parse_cfw_current() -> None:
    v = parse_intent_zh("查询当前滤镜")
    assert v is not None
    assert v.action == "cfw_current"


def test_parse_cfw_list() -> None:
    v = parse_intent_zh("有哪些滤镜可以用")
    assert v is not None
    assert v.action == "cfw_list"


def test_parse_cfw_goto_red() -> None:
    v = parse_intent_zh("切换到红色滤镜")
    assert v is not None
    assert v.action == "cfw_goto"
    assert v.target == "red"


def test_parse_cfw_goto_slot() -> None:
    v = parse_intent_zh("切到4号滤镜")
    assert v is not None
    assert v.action == "cfw_goto"
    assert v.target == "4"


def test_parse_cfw_goto_ha() -> None:
    v = parse_intent_zh("换成Ha滤镜")
    assert v is not None
    assert v.action == "cfw_goto"
    assert v.target == "ha"


def test_parse_usb_devices_pi() -> None:
    v = parse_intent_zh("当前有哪些设备连接到pi")
    assert v is not None
    assert v.action == "usb_devices"


def test_parse_usb_devices_query() -> None:
    v = parse_intent_zh("查询usb连接的设备")
    assert v is not None
    assert v.action == "usb_devices"


def test_parse_help_features() -> None:
    v = parse_intent_zh("请介绍一下你的功能")
    assert v is not None
    assert v.action == "help"


def test_parse_help_not_describe() -> None:
    v = parse_intent_zh("请介绍一下你的功能")
    assert v is not None
    assert v.action == "help"
    v2 = parse_intent_zh("介绍一下木星")
    assert v2 is not None
    assert v2.action == "describe"
    assert v2.target == "jupiter"


def test_parse_usb_devices_not_connect_mount() -> None:
    v = parse_intent_zh("连接望远镜")
    assert v is None or v.action == "connect"


def test_parse_nudge_left() -> None:
    v = parse_intent_zh("往左一点")
    assert v is not None
    assert v.action == "nudge"
    assert v.nudge_direction == "left"


def test_parse_nudge_left_with_zhuan() -> None:
    v = parse_intent_zh("往左转一点。")
    assert v is not None
    assert v.action == "nudge"
    assert v.nudge_direction == "left"


def test_try_goto_star_hd_with_space(monkeypatch) -> None:
    def _fake_find_star(name: str) -> tuple[float, float, str]:
        assert name == "HD 224"
        return (0.0, 0.0, "HD 224")

    monkeypatch.setattr("telbot.catalog.find_star", _fake_find_star)
    v = _try_goto_star("帮我找 HD 224", confidence=0.9)
    assert v is not None
    assert v.action == "goto"
    assert v.target == "HD 224"


def test_parse_help_find_polaris(monkeypatch) -> None:
    def _fake_find(name: str) -> tuple[float, float, str]:
        assert "北极" in name
        return (0.0, 89.26, "Polaris")

    monkeypatch.setattr("telbot.catalog.find_star", _fake_find)
    for s in ("帮我找北极星", "帮我找一下北极星", "我想看北极星"):
        v = parse_intent_zh(s)
        assert v is not None, s
        assert v.action == "goto"
        assert v.target is not None and "北极" in v.target
