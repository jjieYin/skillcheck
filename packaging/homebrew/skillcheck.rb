class Skillcheck < Formula
  desc "Local-first Skill inventory, audit and preflight checker"
  homepage "https://github.com/jjieYin/skillcheck"
  version "0.3.0-beta"
  url "https://github.com/jjieYin/skillcheck/releases/download/v0.3.0-beta/skillcheck-0.3.0-beta-macos-arm64.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_SHA256"
  license "MIT"

  def install
    bin.install "skillcheck"
  end

  test do
    assert_match "skillcheck", shell_output("#{bin}/skillcheck version")
  end
end

