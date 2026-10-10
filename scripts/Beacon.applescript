-- Beacon.app: double-click to start Beacon from the drive. No Terminal window.
-- The build script compiles this with osacompile and adds the Beacon icon.
on run
	set appPath to POSIX path of (path to me)
	set beaconFolder to do shell script "dirname " & quoted form of appPath
	set launcher to beaconFolder & "/app/scripts/launch.sh"
	try
		do shell script "/bin/bash " & quoted form of launcher & " background"
	on error errMsg
		display dialog "Beacon couldn't start." & return & return & errMsg ¬
			buttons {"OK"} default button "OK" with title "Beacon" with icon caution
	end try
end run
