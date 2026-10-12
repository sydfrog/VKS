@echo off
rem Fake launcher shaped like Broadcom's: forwards all arguments to the program.
"%FAKE_CLI_NODE%" "%~dp0fake-cli.js" %*
exit /b %ERRORLEVEL%
