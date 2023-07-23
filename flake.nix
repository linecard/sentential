{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = builtins.currentSystem;
      pkgs = nixpkgs.legacyPackages.${system};
      name = "sentential";
      version = "0.12.1";
      src = ./.;

      site-packages = pkgs.stdenv.mkDerivation rec {
        inherit name version src;
        __noChroot = true;
        POETRY_VIRTUALENVS_CREATE = false;
        buildInputs = with pkgs; [ python311 python311.pkgs.pip poetry pkgs.docker-client ];

        configurePhase = ''
          mkdir -p $out
          poetry export --without-hashes -o $out/requirements.txt
        '';

        buildPhase = ''
          poetry build
        '';

        installPhase = ''
          pip install --prefix $out -r $out/requirements.txt
          pip install --prefix $out dist/${name}-${version}.tar.gz
        '';
      };

      image = pkgs.dockerTools.streamLayeredImage {
        inherit name;
        tag = version;
        contents = [ site-packages pkgs.python311 pkgs.docker-client ];
        config = {
          Env = [ 
            "PYTHONPATH=${site-packages}/lib/python3.11/site-packages/"
            "PATH=${site-packages}/bin:$PATH "
          ];
          Entrypoint = [ "sntl" ];
          Cmd = [ "--help" ];
        }; 
      };

      debug = pkgs.mkShell {
        packages = [ site-packages pkgs.python311 ];
        shellhook = ''
          PYTHONPATH=${site-packages}/lib/python3.11/site-packages/
          PATH=${site-packages}/bin:$PATH
        '';
      };

    in
      {
        packages.${system} = {
          default = site-packages;
          image = image;
        };

        devShells.${system} = {
          default = debug;
        };
      };
}