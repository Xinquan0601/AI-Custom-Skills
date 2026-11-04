<#
  把仓库里每个技能目录挂到 .dsh/skills/ 下（目录 junction，不复制文件）。

    pwsh link-skills.ps1              # 全部
    pwsh link-skills.ps1 work-report  # 指定一个
    pwsh link-skills.ps1 -Prune       # 顺手清掉指向已删除目录的失效链接
#>
param([string[]]$Name, [switch]$Prune)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $repo ".dsh\skills"
New-Item -ItemType Directory -Path $dest -Force | Out-Null

$skills = if ($Name) { $Name } else {
    Get-ChildItem $repo -Directory |
        Where-Object { $_.Name -notin @(".dsh", ".git", "trees") -and (Test-Path (Join-Path $_.FullName "SKILL.md")) } |
        Select-Object -ExpandProperty Name
}

foreach ($s in $skills) {
    $src = Join-Path $repo $s
    if (-not (Test-Path (Join-Path $src "SKILL.md"))) { Write-Host "跳过 $s：没有 SKILL.md"; continue }
    $link = Join-Path $dest $s
    $item = Get-Item $link -Force -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType -eq "Junction") { Remove-Item $link -Force }
    elseif ($item) { Write-Host "冲突 $s：$link 已存在且不是 junction，先手动处理"; continue }
    New-Item -ItemType Junction -Path $link -Target $src | Out-Null
    Write-Host "挂载 $s -> $src"
}

if ($Prune) {
    Get-ChildItem $dest -Force | Where-Object { $_.LinkType -eq "Junction" -and -not (Test-Path $_.Target) } |
        ForEach-Object { Remove-Item $_.FullName -Force; Write-Host "清理失效链接 $($_.Name)" }
}
