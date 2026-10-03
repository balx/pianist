{
  description = "pianist: sheet music transcription -> expressive solo piano performance";

  # unstable: the Claude reader needs a current anthropic SDK (stable 26.05 has 0.97, without fallbacks).
  # flake.lock pins it; after `nix flake update`, rebuild the sample and review its diff (see CLAUDE.md).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-darwin" "x86_64-linux" "aarch64-linux" ]; # nixpkgs no longer builds for Intel Macs
      each = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # Pinned piano samples from freepats.zenvoid.org; only the .sf2 is kept.
      soundfont = pkgs: { name, url, hash, sf2 }:
        pkgs.runCommand name { src = pkgs.fetchurl { inherit url hash; }; nativeBuildInputs = [ pkgs.p7zip ]; } ''
          mkdir -p $out x && cd x
          case $src in *.7z) 7z x $src >/dev/null ;; *) tar xf $src ;; esac
          cp "$(find . -name '${sf2}')" $out/${sf2}
        '';
      soundfonts = pkgs: {
        # Salamander Grand Piano V3, CC BY 3.0 (Alexander Holm), 1.2 GB
        salamander = "${soundfont pkgs {
          name = "salamander-grand-piano-sf2";
          sf2 = "SalamanderGrandPiano-V3+20200602.sf2";
          url = "https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SF2-V3+20200602.tar.xz";
          hash = "sha256-Fe2wYde6YNWDMvctuo+M5AmIBIzHA/k15jIPN9ZQ4hM=";
        }}/SalamanderGrandPiano-V3+20200602.sf2";
        # Upright Piano KW, CC0, 55 MB
        upright = "${soundfont pkgs {
          name = "upright-piano-kw-sf2";
          sf2 = "UprightPianoKW-20220221.sf2";
          url = "https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-SF2-20220221.7z";
          hash = "sha256-F8CExuQgUjPcSbNOS8RKmy18eiwCsEcp7Np3B5sHyCY=";
        }}/UprightPianoKW-20220221.sf2";
      };

      tools = pkgs: [
        (pkgs.python3.withPackages (p: [ p.mido p.pytest p.pytest-xdist p.anthropic ]))
        (pkgs.callPackage ./nix/homr.nix { }) # optical music recognition: --reader omr
        pkgs.poppler-utils # pdftoppm: PDF sheets -> page images for homr
        pkgs.abcmidi # abc2midi
        pkgs.abcm2ps
        pkgs.librsvg # rsvg-convert, score SVG -> PNG
        pkgs.fluidsynth
        pkgs.sox
        pkgs.ffmpeg
        pkgs.ruff # lint: ruff check
      ];
    in
    {
      devShells = each (pkgs: {
        # Both pianos. The first `nix develop` downloads about 1.2 GB of samples into the nix store.
        default = pkgs.mkShell {
          packages = tools pkgs;
          PIANIST_SF_SALAMANDER = (soundfonts pkgs).salamander;
          PIANIST_SF_UPRIGHT = (soundfonts pkgs).upright;
        };
        # CI, or a lighter start (`nix develop .#ci`): every tool and the 55 MB upright only.
        ci = pkgs.mkShell {
          packages = tools pkgs;
          PIANIST_SF_UPRIGHT = (soundfonts pkgs).upright;
        };
      });
    };
}
