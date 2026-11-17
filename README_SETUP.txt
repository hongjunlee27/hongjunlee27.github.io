CONFERENCE TRACKER - INSTALLATION
=================================
1. Place the contents of this package into the ROOT of the existing GitHub Pages repository.
   Do not replace the root index.html. The new web page is conferences/index.html.
2. Create a Tavily account at https://app.tavily.com/ and copy the Tavily API key.
3. GitHub repository > Settings > Secrets and variables > Actions >
   New repository secret. Name it TAVILY_API_KEY and paste the key.
4. IMPORTANT: In GitHub repository Settings > Pages > Build and deployment,
   change Source to "GitHub Actions". The supplied workflow deploys the page
   itself. This avoids the GitHub restriction that GITHUB_TOKEN commits do not
   trigger Pages builds when publishing from a branch.
5. Commit and push all files (including the hidden .github folder).
   Settings > Actions > General: ensure repository policy permits the workflow
   to write repository contents.
6. Repository > Actions > Update and deploy conferences > Run workflow,
   for the first search and deploy. (Normal pushes also deploy without searching.)
7. Visit https://hongjunlee27.github.io/conferences/ after deployment.

AUTOMATION
----------
Every Friday at 09:17 Korea time (00:17 UTC), GitHub Actions searches and adds
qualifying future/current conferences to conferences/events.json. The page
calculates ongoing/upcoming/past using local calendar time on each visit.
No saved conference is removed by automation, but links may later 404.

IMPORTANT LIMITATIONS
---------------------
* New results require explicit readable dates and topic/speaker confirmation.
* Search may miss events, misread calendar ranges, or yield some false matches;
  review newly added entries against original organizer pages.
* This is a discovery aid, not an authoritative complete conference database.
* Search service credits/availability may change; failed runs keep older data.
* Scheduled GitHub workflows may run late or be dropped, and in public repos
  can be automatically disabled after 60 days without activity.
* To add an event manually, insert an entry into conferences/events.json using
  fields title, url, start, end, location, matched_keywords, matched_people.
  The script preserves manual entries.
* Open conferences/index.html via the deployed site or a local HTTP server;
  file:// URLs may prevent the JSON fetch.
