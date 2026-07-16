from __future__ import annotations

import pytest

from pymol_cli.main import (
    CLIError,
    build_launch_command,
    generate_ligand_pocket_pml,
    generate_load_pml,
    generate_render_pml,
    parse_mapping,
    split_csv,
)


def test_split_csv_trims_items() -> None:
    assert split_csv("A, B,C") == ["A", "B", "C"]


def test_parse_mapping_rejects_missing_colon() -> None:
    with pytest.raises(CLIError):
        parse_mapping(["Ared"])


def test_launch_command_adds_remote_before_script() -> None:
    command = build_launch_command(
        "nix run nixpkgs#pymol --",
        remote=True,
        script="show.pml",
        extra_args=["--", "-q"],
    )
    assert command == ["nix", "run", "nixpkgs#pymol", "--", "-R", "-q", "show.pml"]


def test_load_generates_basic_cartoon_view() -> None:
    pml = generate_load_pml(
        path="structures/my protein.cif",
        object_name="prot",
        style="cartoon",
        color="gray70",
        orient=True,
        zoom_buffer=6.0,
    )
    assert pml == [
        'load "structures/my protein.cif", prot',
        "hide everything, prot",
        "show cartoon, prot and polymer",
        "color gray70, prot",
        "orient prot",
        "zoom prot, 6",
    ]


def test_render_generates_png_after_optional_ray() -> None:
    assert generate_render_pml(
        output="outputs/view.png", width=800, height=600, dpi=150, ray=True
    ) == [
        "ray 800,600",
        'png "outputs/view.png", 800, 600, dpi=150',
    ]


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
