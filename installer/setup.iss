; Parallels SQL Admin installer
; Автоматически устанавливает codesign.cer в системные хранилища
; Trusted Root и Trusted Publishers (требует прав администратора, UAC).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define MyAppName "Parallels SQL Admin"
#define MyAppPublisher "alekos corp"
#define MyAppExeName "Parallels SQL Admin.exe"

[Setup]
AppId={{BD65671E-4A64-4703-8B98-37A4F6E6639D}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=ParallelsSQLAdmin-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\ParallelsSQLAdmin.ico
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Parallels SQL Admin\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
Source: "..\codesign.cer"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "certutil.exe"; Parameters: "-addstore -f Root ""{app}\codesign.cer"""; StatusMsg: "Установка сертификата доверия..."; Flags: runhidden
Filename: "certutil.exe"; Parameters: "-addstore -f TrustedPublisher ""{app}\codesign.cer"""; StatusMsg: "Установка сертификата издателя..."; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UpdateApiUrl = 'https://api.github.com/repos/alekosExclusiveVersion/parallels-sql-admins/releases/latest';
  UpdateSetupPrefix = 'ParallelsSQLAdmin-Setup-';
  UpdateSetupLocal = 'ParallelsSQLAdmin-Setup-latest.exe';

var
  DownloadPage: TOutputProgressWizardPage;

{ Поиск подстроки с позиции Offset (аналог 3-арг. Pos из Inno 6.4+). }
function PosFrom(const Substr, Str: String; const Offset: Integer): Integer;
var
  I, MaxI, SubLen: Integer;
begin
  Result := 0;
  SubLen := Length(Substr);
  MaxI := Length(Str) - SubLen + 1;
  if (SubLen = 0) or (Offset < 1) or (Offset > MaxI) then
    Exit;
  for I := Offset to MaxI do
    if Copy(Str, I, SubLen) = Substr then
    begin
      Result := I;
      Exit;
    end;
end;

{ Вытаскивает "tag_name" из JSON-ответа GitHub API (без JSON-парсера). }
function ExtractTagName(const JsonText: String): String;
var
  Key, QuoteEnd: Integer;
  Tag: String;
begin
  Result := '';
  Key := Pos('"tag_name":"', JsonText);
  if Key = 0 then
    Exit;
  QuoteEnd := PosFrom('"', JsonText, Key + 12);
  if QuoteEnd = 0 then
    Exit;
  Tag := Copy(JsonText, Key + 12, QuoteEnd - Key - 12);
  if Copy(Tag, 1, 1) = 'v' then
    Delete(Tag, 1, 1);
  Result := Tag;
end;

{ Возвращает browser_download_url для Setup.exe. }
function ExtractSetupUrl(const JsonText: String): String;
var
  KeyStart, UrlStart, UrlEnd: Integer;
  Url: String;
begin
  Result := '';
  KeyStart := Pos('"browser_download_url":"', JsonText);
  while KeyStart > 0 do
  begin
    UrlStart := KeyStart + 23;
    UrlEnd := PosFrom('"', JsonText, UrlStart);
    if UrlEnd = 0 then
      Exit;
    Url := Copy(JsonText, UrlStart, UrlEnd - UrlStart);
    if Pos(UpdateSetupPrefix, Url) > 0 then
    begin
      Result := Url;
      Exit;
    end;
    KeyStart := PosFrom('"browser_download_url":"', JsonText, UrlEnd + 1);
  end;
end;

{ Детерминированный URL установщика для версии (формат с v4.24.8). }
function SetupUrlForVersion(const Version: String): String;
var
  V: String;
begin
  V := Version;
  if Copy(V, 1, 1) = 'v' then
    Delete(V, 1, 1);
  Result := 'https://github.com/alekosExclusiveVersion/parallels-sql-admins/' +
            'releases/download/v' + V + '/' + UpdateSetupPrefix + V + '.exe';
end;

{ GET последнего релиза (WinHttpRequest; ошибки сети -> пустая строка). }
function FetchLatestReleaseJson(): String;
var
  Http: Variant;
begin
  Result := '';
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open('GET', UpdateApiUrl, False);
    Http.SetRequestHeader('User-Agent', 'ParallelsSQLAdmin-Setup');
    Http.SetTimeouts(8000, 8000, 8000, 20000);
    Http.Send;
    Result := Http.ResponseText;
  except
    Result := '';
  end;
end;

procedure ParseVersion(const V: String; var Major, Minor, Build: Integer);
var
  P1, P2: Integer;
begin
  Major := 0; Minor := 0; Build := 0;
  P1 := Pos('.', V);
  if P1 = 0 then
    Exit;
  P2 := PosFrom('.', V, P1 + 1);
  if P2 = 0 then
    Exit;
  Major := StrToIntDef(Copy(V, 1, P1 - 1), 0);
  Minor := StrToIntDef(Copy(V, P1 + 1, P2 - P1 - 1), 0);
  Build := StrToIntDef(Copy(V, P2 + 1, 16), 0);
end;

function IsNewer(const NewVersion, CurrentVersion: String): Boolean;
var
  NMaj, NMin, NBuild, CMaj, CMin, CBuild: Integer;
begin
  ParseVersion(NewVersion, NMaj, NMin, NBuild);
  ParseVersion(CurrentVersion, CMaj, CMin, CBuild);
  if NMaj <> CMaj then
    Result := NMaj > CMaj
  else if NMin <> CMin then
    Result := NMin > CMin
  else
    Result := NBuild > CBuild;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if (DownloadPage <> nil) and (ProgressMax > 0) then
    DownloadPage.SetProgress(Progress, ProgressMax);
  Result := True;
end;

{ Проверка обновлений до начала установки. }
function InitializeSetup(): Boolean;
var
  Json, LatestVersion, SetupUrl, DownloadPath: String;
  ResultCode: Integer;
begin
  Result := True;

  { Закрываем запущенное приложение, если оно открыто (обновление файлов).
    taskkill молча, ошибки не критичны — CloseApplications всё равно
    закрывает программы, использующие обновляемые файлы. }
  try
    Exec('taskkill.exe', '/F /T /IM "{#MyAppExeName}"', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
  except
  end;

  Json := FetchLatestReleaseJson();
  LatestVersion := ExtractTagName(Json);
  if LatestVersion = '' then
    Exit; { нет сети / API недоступен — ставим текущую версию }

  if not IsNewer(LatestVersion, '{#AppVersion}') then
    Exit; { текущий установщик актуален }

  SetupUrl := ExtractSetupUrl(Json);
  if SetupUrl = '' then
    SetupUrl := SetupUrlForVersion(LatestVersion); { детерминированный фолбэк }
  if SetupUrl = '' then
    Exit;

  if MsgBox('Доступна новая версия ' + LatestVersion + '.' + #13#10#13#10 +
            'Скачать и установить её сейчас?' + #13#10 +
            '(иначе будет установлена текущая версия {#AppVersion})',
            mbConfirmation, MB_YESNO) <> IDYES then
    Exit;

  DownloadPage := CreateProgressPage(
    'Скачивание установщика',
    'Скачивание установщика версии ' + LatestVersion + '...');
  DownloadPage.Show;

  DownloadPath := ExpandConstant('{tmp}\' + UpdateSetupLocal);
  try
    if not DownloadTemporaryFile(SetupUrl, UpdateSetupLocal, '', @OnDownloadProgress) then
    begin
      DownloadPage.Hide;
      MsgBox('Не удалось скачать установщик новой версии.' + #13#10 +
             'Будет установлена текущая версия {#AppVersion}.',
             mbError, MB_OK);
      Exit;
    end;
  except
    DownloadPage.Hide;
    MsgBox('Ошибка скачивания установщика новой версии.' + #13#10 +
           'Будет установлена текущая версия {#AppVersion}.',
           mbError, MB_OK);
    Exit;
  end;
  DownloadPage.Hide;

  if FileExists(DownloadPath) then
  begin
    if Exec(DownloadPath, '', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
    begin
      if ResultCode = 0 then
        Result := False { новая версия установлена — текущую отменяем }
      else
        MsgBox('Установщик новой версии завершился с ошибкой (код ' +
               IntToStr(ResultCode) + ').' + #13#10 +
               'Будет установлена текущая версия {#AppVersion}.',
               mbError, MB_OK);
    end
    else
      MsgBox('Не удалось запустить установщик новой версии.' + #13#10 +
             'Будет установлена текущая версия {#AppVersion}.',
             mbError, MB_OK);
  end
  else
    MsgBox('Скачанный файл не найден: ' + DownloadPath + #13#10 +
           'Будет установлена текущая версия {#AppVersion}.',
           mbError, MB_OK);
end;