# Copyright (c) 2026 Seungwon Lee
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from pymol_cli.main import (
    CLIError,
    build_launch_command,
    generate_ligand_pocket_pml,
    generate_load_pml,
    generate_render_pml,
    parse_mapping,
    require_mark_residues,
    resolve_ligand_chains,
    split_csv,
    split_mark_residues,
)


def test_split_csv_trims_items() -> None:
    assert split_csv("A, B,C") == ["A", "B", "C"]


def test_parse_mapping_rejects_missing_colon() -> None:
    with pytest.raises(CLIError):
        parse_mapping(["Ared"])


def test_launch_command_adds_remote_before_script() -> None:
    command = build_launch_command(
        "pymol",
        remote=True,
        headless=False,
        script="show.pml",
        extra_args=["--", "-q"],
    )
    assert command == ["pymol", "-R", "-q", "show.pml"]


def test_launch_command_adds_headless_flags() -> None:
    command = build_launch_command(
        "pymol",
        remote=True,
        headless=True,
        script=None,
        extra_args=[],
    )
    assert command == ["pymol", "-R", "-cq"]


def test_load_generates_basic_cartoon_view() -> None:
    pml = generate_load_pml(
        path="structures/my protein.cif",
        object_name="prot",
        style="cartoon",
        color="gray70",
        orient=True,
        zoom_buffer=6.0,
        allow_url=False,
    )
    assert pml == [
        'load "structures/my protein.cif", prot',
        "hide everything, prot",
        "show cartoon, prot and polymer",
        "color gray70, prot",
        "orient prot",
        "zoom prot, 6",
    ]


def test_load_rejects_urls_without_opt_in() -> None:
    with pytest.raises(CLIError, match="--allow-url"):
        generate_load_pml(
            path="https://example.org/model.cif",
            object_name="prot",
            style="none",
            color=None,
            orient=False,
            zoom_buffer=0,
            allow_url=False,
        )


def test_load_allows_urls_when_explicit() -> None:
    pml = generate_load_pml(
        path="https://example.org/model.cif",
        object_name="prot",
        style="none",
        color=None,
        orient=False,
        zoom_buffer=0,
        allow_url=True,
    )
    assert pml == ['load "https://example.org/model.cif", prot']


def test_render_generates_png_after_optional_ray() -> None:
    assert generate_render_pml(
        output="outputs/view.png", width=800, height=600, dpi=150, ray=True
    ) == [
        "ray 800,600",
        'png "outputs/view.png", 800, 600, dpi=150',
    ]


def test_partial_ligand_chains_continue_with_present_chains() -> None:
    present, missing = resolve_ligand_chains(
        {"A": 43, "B": 0, "C": 43, "D": 0}, strict=False, ligand="HEM"
    )
    assert present == ["A", "C"]
    assert missing == ["B", "D"]


def test_all_missing_ligand_chains_fail() -> None:
    with pytest.raises(CLIError, match="ligand HEM not found in chains: A,B"):
        resolve_ligand_chains({"A": 0, "B": 0}, strict=False, ligand="HEM")


def test_strict_ligand_chains_fail_on_partial_match() -> None:
    with pytest.raises(CLIError, match="ligand HEM not found in chains: B"):
        resolve_ligand_chains({"A": 43, "B": 0}, strict=True, ligand="HEM")


def test_mark_residues_split_comma_and_pymol_union() -> None:
    assert split_mark_residues("58,87+999") == ["58", "87", "999"]


def test_missing_marked_residue_fails() -> None:
    with pytest.raises(CLIError, match="marked residues not found: A:999"):
        require_mark_residues({"A:58": 10, "A:999": 0})


def test_ligand_pocket_generates_per_chain_views() -> None:
    pml = generate_ligand_pocket_pml(
        object_name="hb",
        ligand="HEM",
        chains=["A", "B"],
        distance=4.0,
        colors={"A": "red", "B": "marine"},
        marks={"A": "58,87", "B": "63,92"},
        grid=True,
        scene="heme_pockets",
        disable_source=True,
    )
    text = "\n".join(pml)
    assert (
        "delete site_A or site_B or pocket_A or pocket_B or mark_A or mark_B or pocket_all"
        in text
    )
    assert "set grid_mode, 1" in text
    assert "create site_A, (hb and chain A)" in text
    assert (
        "select pocket_A, site_A and byres (polymer within 4 of (site_A and resn HEM))"
        in text
    )
    assert "select mark_B, site_B and resi 63+92" in text
    assert 'label (site_A and resn HEM and name FE), "A HEM"' in text
    assert "scene heme_pockets, store" in text


def test_ligand_pocket_cleans_skipped_chain_helpers() -> None:
    pml = generate_ligand_pocket_pml(
        object_name="protein",
        ligand="LIG",
        chains=["A"],
        cleanup_chains=["A", "B"],
        distance=4.0,
        colors={},
        marks={},
        grid=True,
        scene=None,
        disable_source=True,
    )
    assert pml[0] == (
        "delete site_A or site_B or pocket_A or pocket_B or "
        "mark_A or mark_B or pocket_all"
    )
    assert "create site_A, (protein and chain A)" in pml
    assert all("create site_B" not in command for command in pml)


def test_ligand_pocket_rejects_command_like_tokens() -> None:
    with pytest.raises(CLIError):
        generate_ligand_pocket_pml(
            object_name="hb;delete_all",
            ligand="HEM",
            chains=["A"],
            distance=4.0,
            colors={},
            marks={},
            grid=False,
            scene=None,
            disable_source=False,
        )
