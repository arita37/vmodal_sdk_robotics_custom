# Robot MCP maintainer guide

The implementation lives in the `vmx_mobile` monorepo. See [installation](docs/install.md),
[robot contracts](docs/robot_contract.md), [sample calls](docs/robot_examples.md) and
[the VLA design](docs/vla_train/01_doc.md).

The robot modules compose the sibling Python SDK. Format registration and local telemetry
storage are MCP responsibilities; server-side storage/filtering changes are outside this
package. Preserve the existing SDK route contract and immutable format versions.

From this package directory with the existing interpreter active:

```bash
export PYTHONPATH="$(pwd)"
python utils.py sdk_version_sync --check=true
bash test.sh test
```

Load `env.sh dev` only for intentional development-gateway calls. Live suites require a valid
`api_key`; `bash test.sh live_mcp` exercises the real protocol and `bash test.sh initial`
uploads, indexes and searches the packaged fixture. Neither is part of offline `test_all`.

The workflow `.github/workflows/sdk_mcp_robot_test_release.yml` follows the reference MCP
workflow's secret-scan, public/repository SDK testing, Infisical and Cloudflare patterns. On
push/PR it runs every offline suite and builds checked wheel/sdist artifacts. Manual
`run_live_tests=true` enables authenticated integration suites. It does not publish to a
public repository; the public destination has not been specified for the robot package.

The source distribution includes samples, skill helpers, tests and docs through `MANIFEST.in`.
The wheel contains the runtime; use the source distribution/checkout for skill assets. CI
installs the wheel outside the checkout to verify its executable. Do not export runtime
artifacts, credentials or `ztmp` in a release. Existing copied video-search skills remain
available alongside the new robot-similar skill.
