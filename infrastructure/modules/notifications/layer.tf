# infrastructure/modules/notifications/layer.tf
#
# Terraform-managed Lambda Layer that supplies the alert email Lambda's runtime
# Python dependencies (SQLAlchemy, psycopg2-binary, python-dotenv). The app-code
# zip in lambda.tf deliberately excludes these packages; this layer provides
# them in the layout Lambda expects: a top-level `python/` directory on the
# layer's sys.path.
#
# Build model:
#   1. null_resource.build_alert_email_layer runs `pip install` (local-exec,
#      apply-time only) into build/layer/python using Lambda-compatible wheel
#      selection flags so the wheels are valid on the python3.12 Linux runtime
#      even when `terraform apply` runs on macOS/Windows or a different libc.
#   2. data.archive_file.alert_email_layer zips build/layer into
#      build/alert_email_layer.zip, AFTER the pip install completes, via an
#      explicit depends_on so the zip reflects the freshly installed packages
#      and not a stale/empty directory.
#   3. aws_lambda_layer_version.alert_email publishes the zip.
#
# Provisioners do not run during `terraform validate` or `terraform plan`; pip
# is invoked once on first `terraform apply` and only re-invoked when the
# requirements.txt hash changes (see `triggers`). `archive_file` is deferred to
# apply via depends_on, so a first plan does not fail on a missing build dir and
# does not publish an empty layer.
#
# Toggle: set var.create_alert_email_lambda_layer=false to skip Terraform-owned
# layer creation and instead pass external layer ARNs through
# var.alert_email_lambda_layer_arns (see lambda.tf for the combined layers list).

# ---------------------------------------------------------------------------
# Build step: install pinned deps into the Lambda layer folder layout.
#
# The python3.12 Lambda runtime resolves layer contents by adding
# /opt/python to sys.path, so packages must land under a top-level `python/`
# directory inside the layer zip. We install straight into build/layer/python
# with --target so the zip root is `python/`.
#
# Lambda-compatibility guards on `pip install`:
#   --platform manylinux2014_x86_64  Only accept wheels tagged for the manylinux
#                                   runtime Lambda uses (Amazon Linux 2). This
#                                   prevents pulling a non-Linux wheel when the
#                                   host running `terraform apply` is macOS or
#                                   Windows. Pure-python (py3-none-any) wheels
#                                   remain valid under this flag.
#   --implementation cp             CPython wheels only.
#   --python-version 3.12           Match the Lambda runtime exactly.
#   --only-binary=:all:             Never build from sdist. psycopg2-binary
#                                   ships a manylinux wheel with libpq
#                                   statically bundled, so this avoids any
#                                   on-host compilation and guarantees a
#                                   Lambda-loadable binary.
#   --no-compile                    Skip .pyc generation; Lambda generates them
#                                   at first invoke and stale bytecode in the
#                                   layer can shadow edits across versions.
#
# These flags mean the layer zip is identical regardless of which OS runs
# `terraform apply` -- the build is reproducible to the wheel selection.
# ---------------------------------------------------------------------------
resource "null_resource" "build_alert_email_layer" {
  count = var.create_alert_email_lambda_layer ? 1 : 0

  # Rebuild only when the pinned requirements change. file() is read at plan,
  # so the trigger is stable across applies until an operator edits the pins.
  triggers = {
    requirements_hash = sha1(file("${path.module}/layers/alert_email/requirements.txt"))
    pip_flags_hash    = sha1("manylinux2014_x86_64|cp|3.12|only-binary")
  }

  provisioner "local-exec" {
    # /bin/bash so we get rm -rf/mkdir -p reliably across hosts.
    interpreter = ["/bin/bash", "-c"]

    # path.module resolves to an absolute path, so the command works regardless
    # of the directory terraform was invoked from (env root vs module root).
    command = <<-EOT
      set -euo pipefail
      rm -rf "${path.module}/build/layer"
      mkdir -p "${path.module}/build/layer/python"
      pip install \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        --no-compile \
        --target "${path.module}/build/layer/python" \
        -r "${path.module}/layers/alert_email/requirements.txt"
    EOT
  }

  # Guard: fail plan loudly if the pinned requirements file is missing. The
  # triggers reference file() on this path, so a missing file would otherwise
  # surface as an opaque hashing error; this turns it into an actionable message.
  # (pip itself must be present on PATH at apply time; that is a documented host
  # prerequisite, not something Terraform can pre-check statically.)
  lifecycle {
    precondition {
      condition     = fileexists("${path.module}/layers/alert_email/requirements.txt")
      error_message = "layers/alert_email/requirements.txt is missing; cannot build the alert email Lambda layer."
    }
  }
}

# ---------------------------------------------------------------------------
# Zip the built layer folder. depends_on defers this data source to the apply
# phase so it runs AFTER null_resource.build_alert_email_layer's pip install,
# not during refresh -- this is what makes the zip reflect the installed
# packages on the very first apply instead of an empty/placeholder directory.
# ---------------------------------------------------------------------------
data "archive_file" "alert_email_layer" {
  count       = var.create_alert_email_lambda_layer ? 1 : 0
  type        = "zip"
  source_dir  = "${path.module}/build/layer"
  output_path = "${path.module}/build/alert_email_layer.zip"
  # Output hash feeds aws_lambda_layer_version.source_code_hash so a new layer
  # version is published only when package contents actually change.
  depends_on = [null_resource.build_alert_email_layer]
}

# ---------------------------------------------------------------------------
# Publish the layer. compatible_runtimes/architectures are locked to the
# python3.12 x86_64 runtime the Lambda is configured for; attaching this layer
# to a different runtime would be rejected by AWS at attach time.
# ---------------------------------------------------------------------------
resource "aws_lambda_layer_version" "alert_email" {
  count            = var.create_alert_email_lambda_layer ? 1 : 0
  layer_name       = "hirenovik-alert-email-${var.environment}"
  filename         = data.archive_file.alert_email_layer[0].output_path
  source_code_hash = data.archive_file.alert_email_layer[0].output_base64sha256

  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]

  # create_before_destroy so a pin change (new source_code_hash) publishes the
  # new version before removing the old one, keeping the Lambda's current layer
  # reference valid throughout the swap.
  lifecycle {
    create_before_destroy = true
  }

  # NOTE: aws_lambda_layer_version does not accept `tags` -- Lambda layers are
  # not taggable through the AWS API. The layer is identified by layer_name +
  # version and surfaced via module outputs; account-level tagging is handled
  # by the provider default_tags block in environments/dev/main.tf.
}

# ---------------------------------------------------------------------------
# Combined layers list attached to the Lambda. Terraform-owned layer first
# (when enabled), then any externally-supplied ARNs (e.g. a shared common-libs
# layer). Keeping this in a local keeps the schedule precondition in sync with
# the same source of truth the Lambda uses.
# ---------------------------------------------------------------------------
locals {
  alert_email_effective_layers = concat(
    var.create_alert_email_lambda_layer ? [aws_lambda_layer_version.alert_email[0].arn] : [],
    var.alert_email_lambda_layer_arns,
  )
}