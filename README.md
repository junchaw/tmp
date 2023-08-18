In order to trouble shoot this, we first need to understand how the runner work and how we configure it: https://confluence.teslamotors.com/display/PLATENG/GitHub+Actions+Runner+Controller, in short:

- Actions Runner Controller maintains a runner pod for each Runner resource, and in our case, the runner pod is ephemeral, which means it will handle only one job and will be deleted once the job is done;
- Again, in our case, we are using the Kubernetes mode, which means the runner does not run the job in itself, instead, it creates a job pod to run the job;
- If you have Docker Container Action step, more Job / Pod will be created to run the Docker Container Action step, but this is not related to our problem;

So firstly we need to confirm where this "Initialize containers" step is from, I re-ran the job with debug logging enabled, and saw the following log:

```text
##[debug]Evaluating condition for step: 'Initialize containers'
##[debug]Evaluating: success()
##[debug]Evaluating success:
##[debug]=> true
##[debug]Result: true
##[debug]Starting: Initialize containers
##[debug]Register post job cleanup for stopping/deleting containers.
Run '/runner/k8s/index.js'
##[debug]/runner/externals/node16/bin/node /runner/k8s/index.js
##[debug]Using image 'docker-hub-remote.artifactory.teslamotors.com/ubuntu:22.04' for job image
##[debug]Job container resources configured to: {"requests":{"memory":"200M","cpu":"200m"},"limits":{"memory":"1Gi","cpu":"1"}}
##[debug]Job pod created, waiting for it to come online actions-runner-controller-rd-dk5k8-sjc5n-workflow
##[debug]Job pod is ready for traffic
##[debug]{"message":"command terminated with non-zero exit code: error executing command [sh -c [ $(cat /etc/*release* | grep -i -e '^ID=*alpine*' -c) != 0 ] || exit 1], exit code 1","details":{"causes":[{"reason":"ExitCode","message":"1"}]}}
##[debug]Setting isAlpine to false
##[debug]Finishing: Initialize containers
```

Apparently this step is from the k8s hook which is used to spin up the job pod, we are using our fork of the hooks so the code is here https://github.tesla.com/platform/runner-container-hooks/tree/main/packages/k8s/src/hooks.

About these hooks, they are Container Hooks, which is used to customize job run process. The repo runner-container-hooks is the official implementation of running job in container, it uses these Container Hooks to implement the main logic. The step "Initialize containers" is actually set by the runner with the registered Container Hook, see https://github.com/actions/runner/blob/b91ad56f922eeb3d64258d9cc3230cf0a580ea22/src/Runner.Worker/JobExtension.cs#L295

By observing the run process, it stuck for 2m before the log "Using image xxx", so I located the code and found the following code in the "prepare_job" hook:

```javascript
if (!args.container) {
  throw new Error('Job Container is required.')
}

await prunePods()
await copyExternalsToRoot()
let container: k8s.V1Container | undefined = undefined
if (args.container?.image) {
  core.debug(`Using image '${args.container.image}' for job image`)
// ...
```

Ok, let's add some debug logging and make a new runner image to see what's going on, after some back and forth debugging, I was able to finally locate the problem:

```javascript
async function copyExternalsToRoot(): Promise<void> {
  core.debug(`Copying externals to root.`)
  const workspace = process.env['RUNNER_WORKSPACE']
  core.debug(`Workspace: ${workspace}`)
  if (workspace) {
    core.debug(`Copying.`)
    // took 2m to copy the files
    await io.cp(
      path.join(workspace, '../../externals'),
      path.join(workspace, '../externals'),
      { force: true, recursive: true, copySourceDirectory: false }
    )
  }
  core.debug(`Copying externals to root complete.`)
}
```

It took 2m to copy the files, I added a sleep before `io.cp` and exec-ed into the pod to check these files, they're being copied from the externals directory built in the runner image to the workspace directory which is mounted from a PersistentVolumeClaim, in our case it's an EFS volume. I did the following check/test:

```shell
# 6715 files
find /runnertmp/externalstmp -type f | wc -l
# 304.56MB
find /runnertmp/externalstmp -type f -exec du -b {} + | awk '{ total += $1 } END { print total/1024/1024 " MB" }'

# local 149M/s
dd if=/dev/zero of=/tmp/test.bin bs=512MB count=1 oflag=dsync
# local 221K/s
dd if=/dev/zero of=/tmp/test.bin bs=512 count=1000 oflag=dsync
# about 100M/s
dd if=/dev/zero of=/_work/test.bin bs=512MB count=1 oflag=dsync
# about 72K/s
dd if=/dev/zero of=/_work/test.bin bs=512 count=1000 oflag=dsync

# 0m38.667s
time (rm -rf /_work/externalstmp)
# 1m15.620s
time (cp -r /runnertmp/externalstmp /_work/externalstmp)
```

As we can see above the volume, or EFS, has a good performance for large files, but it's very slow for small files, and the externals directory contains 6715 files, it should be the reason why it took 2m to run `io.cp`.

Take a look inside the `externals` directory, it contains several versions of node:

```text
node12
node12_alpine
node16
node16_alpine
```

We're always using ubuntu:22.04 as the base runner image, so we're using node16, other versions are not needed.

Also under `node16` directory, three is not only the node binary, but also the `node_modules`, which contains huge number of files, from the code I think the node binary is the only one needed to run hooks, `npm` can be used by user to install more packages, but it could be optional.

So I removed all the unnecessary files and made a new runner image (checkout https://github.tesla.com/platform/runner-container-hooks about how to make a new release), now let's re-run the job:









```text
##[debug]Evaluating condition for step: 'Initialize containers'
##[debug]Evaluating: success()
##[debug]Evaluating success:
##[debug]=> true
##[debug]Result: true
##[debug]Starting: Initialize containers
##[debug]Register post job cleanup for stopping/deleting containers.
Run '/runner/k8s/index.js'
##[debug]/runner/externals/node16/bin/node /runner/k8s/index.js
##[debug]Copying externals to root.
##[debug]Workspace: /runner/_work/actions-runner-test-us-west-2-eng-fleet
##[debug]Copying.
##[debug]Copying externals to root complete.
##[debug]Using image 'docker-hub-remote.artifactory.teslamotors.com/ubuntu:22.04' for job image
##[debug]Job container resources configured to: {"requests":{"memory":"200M","cpu":"200m"},"limits":{"memory":"1Gi","cpu":"1"}}
##[debug]Job pod created, waiting for it to come online actions-runner-controller-rd-dk5k8-sjc5n-workflow
##[debug]Job pod is ready for traffic
##[debug]{"message":"command terminated with non-zero exit code: error executing command [sh -c [ $(cat /etc/*release* | grep -i -e '^ID=*alpine*' -c) != 0 ] || exit 1], exit code 1","details":{"causes":[{"reason":"ExitCode","message":"1"}]}}
##[debug]Setting isAlpine to false
##[debug]Finishing: Initialize containers
```
