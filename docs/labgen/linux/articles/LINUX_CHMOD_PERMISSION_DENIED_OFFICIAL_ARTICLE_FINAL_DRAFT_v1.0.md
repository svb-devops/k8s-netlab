---
status: ready_to_publish_draft
title: "chmod 权限位正确，为什么还是 Permission Denied？"
created_after_lab_validation: true
directus_record_created: false
public_exposure: none
---

# chmod 权限位正确，为什么还是 Permission Denied？

上周处理一个入职流程的小问题：新同事的报告文件读不出来，`cat` 直接报
`Permission denied`。第一反应跟大多数人一样——肯定是权限位设错了，`chmod 644`
上去就完事。结果重新 `chmod 644` 之后，**读取还是失败，一模一样的报错**。

这时候才意识到，问题从来就不在这个文件本身。

## 先看现场

```
$ cat case/vault/report.txt
cat: case/vault/report.txt: Permission denied
```

看起来是权限问题，很自然。查一下文件自己的权限位：

```
$ stat -c %a case/vault/report.txt
644
```

644——`rw-r--r--`，所有者能读写，其他人能读。这个权限位完全正常，没有任何问题。

## 第一反应：再 chmod 一次

多数人（包括我）第一反应都是"权限肯定还是不对，再设一遍"：

```
$ chmod 644 case/vault/report.txt
$ cat case/vault/report.txt
cat: case/vault/report.txt: Permission denied
```

同样的报错，一字不差。这一步很关键——它证明了一件事：**文件自己的权限位从来就没有错过**。
chmod 只能改变你指定的那个路径的权限位，改变不了路径上任何其他目录。如果确认目标文件
本身权限正确之后问题依然存在，根因结构上一定在别的地方——上层目录。

## 真正的原因：目录的 execute 位

Linux 里读一个文件需要两个独立的权限检查同时满足：

1. 文件自身的 read 权限
2. 路径上**每一层目录**的 execute（也叫 traverse，遍历）权限

第二条是最容易被忽略的部分，因为目录的 `ls -l` 输出跟文件长得一样，但 execute
位在目录上的含义完全不同——它表示"能不能进入/遍历这个目录"，跟"能不能执行程序"毫无关系。

顺着路径往上查：

```
$ ls -la case
drwxr-xr-x  ... case

$ stat case
Access: (0755/drwxr-xr-x)

$ stat case/vault
Access: (0600/-rw-------)
```

找到了：`case/vault` 是 `600`——只有读写位，**没有 execute 位，连所有者自己都没有**。
不管 `report.txt` 自己的权限设成什么样，任何进程都无法"进入"这个目录去够到里面的文件。

## 修复：只改根因，不多改一分

```
$ chmod 700 case/vault
$ cat case/vault/report.txt
Q3 onboarding summary: pending review, ticket 4471.
```

读取恢复了。整个过程中，`report.txt` 自己的权限位从头到尾没有被动过——因为它从来就没有错。

选 `700` 而不是 `777` 是有意为之：这是一个单用户的沙箱工作区，所有者自己需要
读写执行权限，完全没有理由把 group/other 的访问权限也放开。`chmod 777` 在这
里"也能解决问题"，但那是意外解决，不是正确答案——它会让这个目录对所有人可写，
这在真实生产环境里是一个真正的安全隐患，而不是权限调试的正确收尾方式。

## 结论

下次看到"权限位看起来完全正确，但还是 Permission denied"，先别急着重新
chmod 目标文件——那一步大概率是白费功夫。往上查一下路径中每一层目录的
execute 位，根因大概率就在那里。

---

> 在一个临时 Linux 环境里，亲手复现一次：
> 文件权限已经正确，但父目录让它依然无法访问。

[在实验室里亲手复现这个场景 →]（internal preview / 即将开放公开访问，占位）
