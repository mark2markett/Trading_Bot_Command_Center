import importlib.util
import json
from pathlib import Path
import pytest
from test_activity_dashboard_install import fixture,installer,protected
ROOT=Path(__file__).parent

def module():
    path=ROOT/'APPLY-TRADING-OVERVIEW.py'
    assert path.exists(),'No display-only trading overview installer'
    spec=importlib.util.spec_from_file_location('overview_installer',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def ready(tmp_path):
    repo,package,payload,fetcher=fixture(tmp_path)
    for name in installer.SOURCE:(repo/name).write_bytes(payload[name])
    return repo,package,payload,fetcher

def test_display_install_changes_no_source_financial_records_or_flags(tmp_path):
    m=module();repo,package,payload,fetcher=ready(tmp_path)
    before=protected(repo);source={name:(repo/name).read_bytes() for name in installer.SOURCE}
    result=m.install(repo,package,fetcher=fetcher)
    assert result['scope']=='DISPLAY_ONLY' and result['ok']
    assert protected(repo)==before
    assert source=={name:(repo/name).read_bytes() for name in installer.SOURCE}
    assert (repo/installer.INDEX).read_bytes()==payload[installer.INDEX]

def test_missing_activity_backend_is_refused_without_copying_files(tmp_path):
    m=module();repo,package,payload,fetcher=fixture(tmp_path)
    with pytest.raises(ValueError,match='activity backend'):m.install(repo,package,fetcher=fetcher)
    assert (repo/installer.INDEX).read_bytes()==b'old index'

def test_stale_served_display_restores_only_index(tmp_path):
    m=module();repo,package,payload,fetcher=ready(tmp_path)
    before=protected(repo);source={name:(repo/name).read_bytes() for name in installer.SOURCE}
    def stale(route):return b'old served index' if route=='/' else fetcher(route)
    with pytest.raises(ValueError,match='Served overview'):m.install(repo,package,fetcher=stale)
    assert (repo/installer.INDEX).read_bytes()==b'old index'
    assert protected(repo)==before
    assert source=={name:(repo/name).read_bytes() for name in installer.SOURCE}

def test_activity_route_failure_is_refused_before_index_change(tmp_path):
    m=module();repo,package,payload,fetcher=ready(tmp_path)
    def invalid(route):return b'{"detail":"not found"}' if route=='/api/activity' else fetcher(route)
    with pytest.raises(ValueError,match='Activity API'):m.install(repo,package,fetcher=invalid)
    assert (repo/installer.INDEX).read_bytes()==b'old index'
